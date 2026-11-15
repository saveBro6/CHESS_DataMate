"""Build the per-database value index that ``retrieve_entity`` fuzzy-matches against.

The index answers one question -- "which stored values look like this word?" -- so it
only carries values that can actually be a literal anchor. Two measured facts shape it:

* **Not every text column belongs in it.** A column whose distinct values cover most of
  its rows (an order timestamp, an order code) can never be matched by a name, and it
  used to be 98% of the indexed values because the column filter was an English keyword
  denylist that Vietnamese headers never match. The filter is now the data's own
  distinct/rows ratio, which is language-blind (see :func:`_is_near_unique`), and it only
  applies to columns large enough to hit the per-column cap -- every smaller column keeps
  its values, because that is where the literal anchors live.
* **Vietnamese is typed both with and without tone marks.** Shingles are therefore the
  union of the NFC-lowercased accented text and its folded, unaccented form, so
  ``sua dac`` and ``Sữa đặc`` overlap instead of only sharing the characters that happen
  to be ASCII.

The four numbers the index is built with travel inside the pickled index, and the query
side (``db_values.search``) reads them back instead of trusting a caller's copy.
"""

import math
import pickle
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from datasketch import MinHash, MinHashLSH
from tqdm import tqdm
import logging

from datamate.questions import fold_vietnamese
from database_utils.execution import execute_sql

# The build and the query side must use the same four numbers; they are recorded in the
# pickle so the query side can prove it agrees with the build instead of assuming it.
LSH_NUM_PERM = 128
LSH_THRESHOLD = 0.4
LSH_SHINGLE_K = 3
LSH_MAX_SAMPLE_VALUES = 10000
LSH_PARAMETER_ATTRIBUTE = "lsh_parameters"
LSH_PARAMETER_NAMES = ("num_perm", "threshold", "shingle_k", "max_sample_values")

# A literal anchor needs repetition: a column where at least every second row carries a
# value of its own is an identifier, a timestamp or a code, not a name. The two counts
# are all the rule reads, so it behaves the same in any language and on any dataset.
NEAR_UNIQUE_DISTINCT_RATIO = 0.5
# Small tables are exempt: with a handful of rows every column looks unique, and the
# per-column sample cap already bounds what such a table can cost. The ratio only gates a
# skip above LSH_MAX_SAMPLE_VALUES distinct values, where the cap would otherwise bite,
# so a small dimension table keeps its names whatever its ratio.
NEAR_UNIQUE_MIN_ROWS = 100


class LSHParametersMissing(RuntimeError):
    """The pickled index carries no build parameters, so it cannot be queried safely."""


def lsh_parameters(lsh: Any) -> Dict[str, Any]:
    """The four numbers the index was built with.

    ``make_db_lsh`` records them on the index before pickling it, so the query side reads
    the build side's own numbers instead of a caller's guess. An index without them was
    built by an older version and cannot be queried consistently, so it is an error
    rather than a silent default.
    """
    parameters = getattr(lsh, LSH_PARAMETER_ATTRIBUTE, None)
    if not isinstance(parameters, dict):
        raise LSHParametersMissing(
            f"the loaded index has no {LSH_PARAMETER_ATTRIBUTE!r} payload; rebuild it with "
            "datamate.ingest.store so the build and the query parameters agree"
        )
    missing = [name for name in LSH_PARAMETER_NAMES if name not in parameters]
    if missing:
        raise LSHParametersMissing(f"the loaded index does not record {', '.join(missing)}")
    return parameters


def check_minhash_parameters(
    minhashes: Dict[str, Tuple[MinHash, str, str, str]],
    parameters: Dict[str, Any],
    sample_only: bool = False,
) -> None:
    """Every stored MinHash must carry the recorded number of permutations.

    A signature of a different length cannot share a bucket with a query sketch, so a
    disagreement here would return nothing at all instead of a bad match. It is cheap to
    prove at load time and the failure is worth an exception.
    """
    expected = int(parameters["num_perm"])
    checked = 0
    for key, entry in minhashes.items():
        checked += 1
        if sample_only and checked > 1:
            break
        length = len(entry[0].digest())
        if length != expected:
            raise LSHParametersMissing(
                f"index stores {length}-permutation MinHashes but records num_perm="
                f"{expected} (first offending key {key!r}); rebuild the artifacts"
            )


def _is_near_unique(
    rows: int, distinct: int, max_sample_values: int = LSH_MAX_SAMPLE_VALUES
) -> bool:
    """True when a column has no repetition for a literal anchor to match against.

    Reads the row count and the distinct count and nothing else: no column name, no
    header, no vocabulary. A column whose distinct values cover at least
    ``NEAR_UNIQUE_DISTINCT_RATIO`` of its rows is one value per row -- a timestamp, an
    order code, a serial -- and every value in it is a dead weight for a name lookup.

    The ratio is the signal, not the gate. Skipping only pays off where the column is
    large in absolute terms, i.e. where it would otherwise hit the per-column sample cap;
    below that the cap already bounds its cost and skipping only loses an anchor. A
    300-row table where every row is a distinct customer name is the case this index
    exists for, so it is indexed in full.
    """
    if distinct < max_sample_values:
        return False
    if rows < NEAR_UNIQUE_MIN_ROWS or distinct < 2:
        return False
    return distinct / rows >= NEAR_UNIQUE_DISTINCT_RATIO


def _cap_values(values: Sequence[str], max_sample_values: int) -> List[str]:
    """Deterministically reduce one column to at most ``max_sample_values`` values.

    Sorting first makes the sample reproducible (``SELECT DISTINCT`` has no defined
    order), and the stride spreads it over the whole column instead of keeping an
    alphabetically-defined head, so the same database always yields the same sample.
    """
    if max_sample_values <= 0 or len(values) <= max_sample_values:
        return list(values)
    step = math.ceil(len(values) / max_sample_values)
    return sorted(values)[::step][:max_sample_values]


def _shingles(text: str, n_gram: int) -> set:
    """Character n-grams of the accented spelling and of its folded form.

    A question may be typed ``sua dac`` while the stored value is ``Sữa đặc``; shingling
    both spellings of each side makes the two overlap, so the index works with or
    without tone marks as the data notes require.
    """
    accented = unicodedata.normalize("NFC", str(text)).strip().lower()
    if not accented:
        return set()
    shingles = set()
    for form in (accented, fold_vietnamese(accented)):
        length = len(form)
        if not length:
            continue
        for index in range(max(1, length - n_gram + 1)):
            piece = form[index : index + n_gram]
            if piece:
                shingles.add(piece)
    return shingles


def _get_unique_values(
    db_path: str, max_sample_values: int = LSH_MAX_SAMPLE_VALUES
) -> Dict[str, Dict[str, List[str]]]:
    """
    Retrieves unique text values from the database excluding primary keys.

    Args:
        db_path (str): The path to the SQLite database file.
        max_sample_values (int): Per-column cap on the number of indexed values.

    Returns:
        Dict[str, Dict[str, List[str]]]: A dictionary containing unique values for each table and column.
    """
    table_names = [table[0] for table in execute_sql(db_path, "SELECT name FROM sqlite_master WHERE type='table';", fetch="all")]
    primary_keys = []

    for table_name in table_names:
        columns = execute_sql(db_path, f"PRAGMA table_info('{table_name}')", fetch="all")
        for column in columns:
            if column[5] > 0:  # Check if it's a primary key
                column_name = column[1]
                if column_name.lower() not in [c.lower() for c in primary_keys]:
                    primary_keys.append(column_name)
    
    unique_values: Dict[str, Dict[str, List[str]]] = {}
    for table_name in table_names:
        if table_name == "sqlite_sequence":
            continue
        logging.info(f"Processing {table_name}")
        try:
            table_rows = execute_sql(db_path, f"SELECT COUNT(*) FROM `{table_name}`", fetch="one", timeout=480)[0] or 0
        except Exception:
            table_rows = 0
        columns = [col[1] for col in execute_sql(db_path, f"PRAGMA table_info('{table_name}')", fetch="all") if ("TEXT" in col[2] and col[1].lower() not in [c.lower() for c in primary_keys])]
        table_values: Dict[str, List[str]] = {}
        
        for column in columns:
            if any(keyword in column.lower() for keyword in ["_id", " id", "url", "email", "web", "time", "phone", "date", "address"]) or column.endswith("Id"):
                continue

            try:
                result = execute_sql(db_path, f"""
                    SELECT SUM(LENGTH(unique_values)), COUNT(unique_values)
                    FROM (
                        SELECT DISTINCT `{column}` AS unique_values
                        FROM `{table_name}`
                        WHERE `{column}` IS NOT NULL
                    ) AS subquery
                """, fetch="one", timeout = 480)
            except:
                result = 0, 0

            sum_of_lengths, count_distinct = result
            if sum_of_lengths is None or count_distinct == 0:
                continue

            average_length = sum_of_lengths / count_distinct
            logging.info(f"Column: {column}, sum_of_lengths: {sum_of_lengths}, count_distinct: {count_distinct}, average_length: {average_length}")

            if _is_near_unique(table_rows, count_distinct, max_sample_values):
                logging.info(
                    "Skipping %s.%s: %d distinct values over %d rows (%.2f of the rows) is "
                    "too close to one value per row to be a literal anchor, and above the "
                    "per-column cap of %d",
                    table_name,
                    column,
                    count_distinct,
                    table_rows,
                    count_distinct / table_rows,
                    max_sample_values,
                )
                continue

            if ("name" in column.lower() and sum_of_lengths < 5000000) or (sum_of_lengths < 2000000 and average_length < 25) or count_distinct < 100:
                logging.info(f"Fetching distinct values for {column}")
                try:
                    values = [str(value[0]) for value in execute_sql(db_path, f"SELECT DISTINCT `{column}` FROM `{table_name}` WHERE `{column}` IS NOT NULL", fetch="all", timeout = 480)]
                except:
                    values = []
                logging.info(f"Number of different values: {len(values)}")
                kept = _cap_values(values, max_sample_values)
                if len(kept) < len(values):
                    logging.info(
                        "Sampling %s.%s: keeping %d of %d distinct values, dropping %d",
                        table_name,
                        column,
                        len(kept),
                        len(values),
                        len(values) - len(kept),
                    )
                table_values[column] = kept
        
        unique_values[table_name] = table_values

    return unique_values

def _create_minhash(signature_size: int, string: str, n_gram: int) -> MinHash:
    """
    Creates a MinHash object for a given string.

    Args:
        signature_size (int): The size of the MinHash signature.
        string (str): The input string to create the MinHash for.
        n_gram (int): The n-gram size for the MinHash.

    Returns:
        MinHash: The MinHash object for the input string.
    """
    m = MinHash(num_perm=signature_size)
    for d in _shingles(string, n_gram):
        m.update(d.encode('utf8'))
    return m

def skip_column(column_name: str, column_values: List[str]) -> bool:
    """
    Determines whether to skip processing a column based on its values.

    Args:
        column_name (str): The name of the column.
        column_values (List[str]): The list of values in the column.

    Returns:
        bool: True if the column should be skipped, False otherwise.
    """
    if "name" in column_name.lower():
        return False
    sum_of_lengths = sum(len(value) for value in column_values)
    average_length = sum_of_lengths / len(column_values)
    return (sum_of_lengths > 50000) and (average_length > 20)

def make_lsh(unique_values: Dict[str, Dict[str, List[str]]], signature_size: int = LSH_NUM_PERM, n_gram: int = LSH_SHINGLE_K, threshold: float = LSH_THRESHOLD, verbose: bool = True) -> Tuple[MinHashLSH, Dict[str, Tuple[MinHash, str, str, str]]]:
    """
    Creates a MinHash LSH from unique values.

    Args:
        unique_values (Dict[str, Dict[str, List[str]]]): The dictionary of unique values.
        signature_size (int): The size of the MinHash signature.
        n_gram (int): The n-gram size for the MinHash.
        threshold (float): The threshold for the MinHash LSH.
        verbose (bool): Whether to display progress information.

    Returns:
        Tuple[MinHashLSH, Dict[str, Tuple[MinHash, str, str, str]]]: The MinHash LSH object and the dictionary of MinHashes.
    """
    lsh = MinHashLSH(threshold=threshold, num_perm=signature_size)
    minhashes: Dict[str, Tuple[MinHash, str, str, str]] = {}
    try:
        total_unique_values = sum(len(column_values) for table_values in unique_values.values() for column_values in table_values.values())
        logging.info(f"Total unique values: {total_unique_values}")
        
        progress_bar = tqdm(total=total_unique_values, desc="Creating LSH") if verbose else None
        
        for table_name, table_values in unique_values.items():
            for column_name, column_values in table_values.items():
                logging.info(f"Processing {table_name} - {column_name} - {len(column_values)}")
                
                for id, value in enumerate(column_values):
                    minhash = _create_minhash(signature_size, value, n_gram)
                    minhash_key = f"{table_name}_{column_name}_{id}"
                    minhashes[minhash_key] = (minhash, table_name, column_name, value)
                    lsh.insert(minhash_key, minhash)
                    
                    if verbose:
                        progress_bar.update(1)
        
        if verbose:
            progress_bar.close()
    except Exception as e:
        logging.error(f"Error creating LSH: {e}")
    
    return lsh, minhashes

def make_db_lsh(db_directory_path: str, signature_size: int = LSH_NUM_PERM, n_gram: int = LSH_SHINGLE_K, threshold: float = LSH_THRESHOLD, max_sample_values: int = LSH_MAX_SAMPLE_VALUES, **kwargs: Any) -> None:
    """
    Creates a MinHash LSH for the database and saves the results.

    The four parameters are recorded inside the pickled index, so a query cannot silently
    run with different numbers than the build used.

    Args:
        db_directory_path (str): The path to the database directory.
        signature_size (int): The size of the MinHash signature.
        n_gram (int): The n-gram size for the MinHash.
        threshold (float): The threshold for the MinHash LSH.
        max_sample_values (int): Per-column cap on the number of indexed values.
        **kwargs (Any): Additional arguments for the LSH creation.
    """
    db_id = Path(db_directory_path).name
    preprocessed_path = Path(db_directory_path) / "preprocessed"
    preprocessed_path.mkdir(exist_ok=True)
    parameters = {
        "num_perm": signature_size,
        "threshold": threshold,
        "shingle_k": n_gram,
        "max_sample_values": max_sample_values,
    }
    
    unique_values = _get_unique_values(str(Path(db_directory_path) / f"{db_id}.sqlite"), max_sample_values=max_sample_values)
    logging.info("Unique values obtained")
    
    with open(preprocessed_path / f"{db_id}_unique_values.pkl", "wb") as file:
        pickle.dump(unique_values, file)
    logging.info("Saved unique values")
    
    lsh, minhashes = make_lsh(unique_values, signature_size=signature_size, n_gram=n_gram, threshold=threshold, **kwargs)
    # The query side rebuilds its MinHash from these numbers, so they are part of the
    # artifact and a self-check runs before it is written.
    setattr(lsh, LSH_PARAMETER_ATTRIBUTE, parameters)
    check_minhash_parameters(minhashes, parameters)
    logging.info(
        "Indexed %d distinct value(s) as %d item(s) with num_perm=%d threshold=%s shingle_k=%d "
        "max_sample_values=%d",
        sum(len(column_values) for table_values in unique_values.values() for column_values in table_values.values()),
        len(minhashes),
        parameters["num_perm"],
        parameters["threshold"],
        parameters["shingle_k"],
        parameters["max_sample_values"],
    )
    
    with open(preprocessed_path / f"{db_id}_lsh.pkl", "wb") as file:
        pickle.dump(lsh, file)
    with open(preprocessed_path / f"{db_id}_minhashes.pkl", "wb") as file:
        pickle.dump(minhashes, file)
