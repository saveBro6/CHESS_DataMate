import json
import re

from workflow.system_state import SystemState
from workflow.agents.tool import Tool

from llm.models import call_engine, get_llm_chain
from llm.prompts import get_prompt

# Turns of the ReAct loop, and how many re-prompts an unparseable turn earns before the
# agent gives up. A model that ignores the tool-calling convention must not abort the
# team: the run ends with the machine-readable abstain below instead of an exception.
MAX_TURNS = 10
MAX_PARSE_RETRIES = 2
NO_TOOL_CALL = "no_tool_call_parsed"

# The state block appended to every agent message is bounded. The evidence pack is
# 34-51 KB and stays in `Task.evidence`, where the tools' own templates read it; the
# agent only needs the question and the columns that exist to pick its next tool.
STATE_BLOCK_CHARS = 4000
STATE_COLUMNS_PER_TABLE = 12
STATE_HISTORY_CHARS = 600
STATE_ECHO_CHARS = 400

_TOOL_CALL_BLOCK = re.compile(r"<tool_call>(.*?)(?:</tool_call>|\Z)", re.S)
_TOOL_NAME_KEYS = ("tool", "tool_name", "name", "function")


def _brace_spans(text: str) -> list[str]:
    """
    Return every balanced `{...}` span of a text, outermost first.

    Models wrap their tool call in fences, prose or both; scanning for balanced spans
    costs nothing and finds the object `json.loads` cannot reach on its own.
    """
    spans = []
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start:index + 1])
    return spans


def _clip(text: str, limit: int) -> str:
    """Collapse whitespace and clip, for the bounded parts of a prompt."""
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


class Agent:
    """
    Abstract base class for agents.
    """
    
    def __init__(self, name: str, task: str, config: dict):
        self.name = name
        self.task = task
        self.config = config
        self.tools_config = config["tools"]
        self.tools = {}
        self.chat_history = []
    
    def workout(self, system_state: SystemState) -> SystemState:
        """
        Abstract method to process the system state.

        Args:
            system_state (SystemState): The current system state.

        Returns:
            SystemState: The processed system state.
        """
        
        system_prompt = get_prompt(template_name="agent_prompt")
        system_prompt = system_prompt.format(agent_name=self.name, 
                                             task=self.task, 
                                             tools=self.get_tools_description())
        self.chat_history.append({"role": "system", "content": system_prompt})
        
        parse_failures = 0
        try:
            for i in range(MAX_TURNS):
                response = self.call_agent(system_state)
                print(f"Agent {self.name} response: {response}")
                tool_name = self.get_next_tool_name(response)
                if tool_name is None:
                    # "DONE" is only trusted when the turn carries no callable tool: a
                    # reply that names a tool is a tool call, whatever else it says.
                    if self.is_done(response):
                        break
                    parse_failures += 1
                    self.handle_unparsed_turn(system_state, response, parse_failures)
                    if parse_failures > MAX_PARSE_RETRIES:
                        break
                    continue
                parse_failures = 0
                self.chat_history.append({"role": "agent", "content": f"<tool_call>{tool_name}</tool_call>"})
                tool = self.tools[tool_name]
                try:
                    tool_response = self.call_tool(tool, system_state)
                    self.chat_history.append({"role": "tool_message", "content": tool_response})
                except Exception as e:
                    print(f"Error in tool {tool_name}: {e}")
        except Exception as e:
            print(f"Error in agent {self.name}: {e}")
            
        return system_state

    def call_tool(self, tool: Tool, system_state: SystemState) -> SystemState:
        """
        Call a tool with the given name and system state.
        """
        try:
            tool(system_state)
            return f"Tool {tool.tool_name} called successfully."
        except Exception as e:
            raise e
        
    def is_done(self, response: str) -> bool:
        """
        Check if the response indicates that the agent is done.
        """
        if "DONE" in response:
            return True
        return False
    
    def get_next_tool_name(self, response: str) -> str | None:
        """
        Return the tool the response asks to call, or None when no call can be parsed.

        Three shapes of the same request are accepted, because models emit all of them:

        - the bare tool name inside the tags, `<tool_call>revise</tool_call>`;
        - a JSON object carrying the name under `tool` / `tool_name` / `name` /
          `function`, with whatever parameter shape the model likes
          (`{"tool": "extract_keywords", "parameters": {}}`);
        - the same JSON embedded in prose or a code fence.

        Parsing never raises: an unrecognisable turn returns None and the caller decides
        whether to re-prompt.
        """
        for payload, in_tags in self._tool_call_payloads(response):
            tool_name = self._tool_name_in(payload, allow_prose=in_tags)
            if tool_name:
                return tool_name
        return None

    def _tool_call_payloads(self, response: str) -> list[tuple[str, bool]]:
        """
        Every place a call can hide: the `<tool_call>` bodies first, else the whole reply.
        """
        text = str(response or "")
        payloads = [(match.group(1), True) for match in _TOOL_CALL_BLOCK.finditer(text)]
        if not payloads:
            payloads.append((text, False))
        return payloads

    def _tool_name_in(self, payload: str, allow_prose: bool = False) -> str | None:
        """
        The tool name carried by one payload, if any.

        `allow_prose` is true only inside `<tool_call>` tags, where a stray mention of
        another tool's name is not a risk; an untagged reply has to carry a real JSON
        object to be trusted.
        """
        body = payload.strip().strip("`").strip()
        if body in self.tools:
            return body
        for mapping in self._json_mappings(body):
            tool_name = self._tool_name_from_mapping(mapping)
            if tool_name:
                return tool_name
        if not allow_prose:
            return None
        for tool_name in sorted(self.tools, key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(tool_name)}(?!\w)", body):
                return tool_name
        return None

    @staticmethod
    def _json_mappings(body: str) -> list[dict]:
        """
        Decode the payload as JSON, or every balanced object inside it.
        """
        mappings = []
        try:
            decoded = json.loads(body)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            mappings.append(decoded)
            return mappings
        for span in _brace_spans(body):
            try:
                decoded = json.loads(span)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict):
                mappings.append(decoded)
        return mappings

    def _tool_name_from_mapping(self, mapping: dict) -> str | None:
        """
        The tool name a decoded JSON object declares, if it names one of this agent's tools.

        `{"function": {"name": ...}}` nests the call one level down, and some gateways add
        a nested `parameters` object, so the declared keys are tried before a shallow walk.
        """
        for key in _TOOL_NAME_KEYS:
            if key not in mapping:
                continue
            value = mapping[key]
            if isinstance(value, str):
                if value.strip() in self.tools:
                    return value.strip()
            elif isinstance(value, dict):
                tool_name = self._tool_name_from_mapping(value)
                if tool_name:
                    return tool_name
        for value in mapping.values():
            if isinstance(value, dict):
                tool_name = self._tool_name_from_mapping(value)
                if tool_name:
                    return tool_name
        return None

    def handle_unparsed_turn(self, system_state: SystemState, response: str, attempt: int) -> None:
        """
        Re-prompt a bounded number of times, then record the abstain on the state.

        The model is shown its own turn plus the exact calling convention; once
        `MAX_PARSE_RETRIES` re-prompts are spent, `state.errors` carries
        `no_tool_call_parsed`, which the bridge turns into an abstain reason instead of
        letting the team fail.
        """
        echo = _clip(response, STATE_ECHO_CHARS) or "(empty response)"
        if attempt <= MAX_PARSE_RETRIES:
            self.chat_history.append({"role": "agent", "content": echo})
            self.chat_history.append(
                {
                    "role": "tool_message",
                    "content": (
                        "No tool call could be parsed from that message. Reply with exactly "
                        f"<tool_call>TOOL_NAME</tool_call>, where TOOL_NAME is one of: "
                        f"{', '.join(self.tools)}. No prose, no JSON, no parameters."
                    ),
                }
            )
            print(f"Agent {self.name} turn {attempt}: no tool call parsed; re-prompting")
            return
        system_state.errors[self.name] = (
            f"{NO_TOOL_CALL}: {MAX_PARSE_RETRIES} re-prompt(s) spent without a parsable "
            f"tool call; last response: <{echo}>"
        )
        print(f"Agent {self.name}: no tool call parsed after {MAX_PARSE_RETRIES} re-prompts; abstaining")

    def call_agent(self, system_state: SystemState) -> SystemState:
        """
        Call the agent with the given system state.
        """
        
        messages = ""
        for chat in self.chat_history:
            role = chat["role"]
            content = chat["content"]
            messages += f"<{role}>\n{content}\n</{role}>\n"
        messages += self.get_state_block(system_state)
        messages += f"<agent>\n"
        
        llm_chain = get_llm_chain(engine_name=self.config["engine"], temperature=0)
        response = call_engine(message=messages, engine=llm_chain)
        return response

    def get_state_block(self, system_state: SystemState) -> str:
        """
        The bounded system state the prompt template promises, ready to append.

        Without it the model is asked to choose a tool while seeing only the placeholder
        the templates carry. The evidence pack is deliberately NOT repeated here: it is
        34-51 KB, it already reaches the tools through `Task.evidence`, and duplicating it
        into every agent turn would double the prompt for no extra grounding.
        """
        lines = ["<state>"]
        try:
            task = getattr(system_state, "task", None)
            question = _clip(getattr(task, "question", "") or "", STATE_HISTORY_CHARS)
            db_id = _clip(getattr(task, "db_id", "") or "", 80)
            lines.append(f"QUESTION: {question or '(missing)'}")
            lines.append(f"DB_ID: {db_id or '(missing)'}")
            lines.append("SCHEMA (table: columns):")
            schema = getattr(system_state, "tentative_schema", None) or {}
            for table_name in sorted(schema):
                columns = [str(column) for column in (schema[table_name] or [])]
                shown = columns[:STATE_COLUMNS_PER_TABLE]
                hidden = len(columns) - len(shown)
                rendered = ", ".join(shown) + (f", … (+{hidden} more)" if hidden > 0 else "")
                lines.append(f"- {table_name}: {rendered}")
            history = getattr(system_state, "execution_history", None) or []
            if history:
                calls = [
                    f"{entry.get('tool_name')}({entry.get('status', 'unknown')})"
                    for entry in history
                    if isinstance(entry, dict) and entry.get("tool_name")
                ]
                lines.append("TOOL CALLS SO FAR: " + ", ".join(calls))
        except Exception as e:
            # A state this agent cannot read must degrade to a shorter prompt, never to a
            # failed run: the tools read the state directly and do not need this block.
            print(f"Error building the state block for agent {self.name}: {e}")
        lines.append("</state>")
        return "\n".join(lines)[:STATE_BLOCK_CHARS] + "\n"

    def get_tools_description(self) -> str:
        """
        Get the description of the tools.
        """
        tools_description = ""
        for i, tool in enumerate(self.tools):
            tools_description += f"{i+1}. {tool}\n"
        return tools_description
    
    def __call__(self, system_state: SystemState) -> SystemState:
        return self.workout(system_state)
