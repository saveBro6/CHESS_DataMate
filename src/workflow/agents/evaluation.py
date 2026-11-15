from typing import Dict

from runner.logger import Logger
from runner.database_manager import DatabaseManager
from workflow.system_state import SystemState
from workflow.agents.tool import Tool

class ExecutionAccuracy(Tool):
    """
    Tool for executing the predicted SQL queries and recording their execution status.

    DataMate tasks carry no gold SQL, so this tool never compares against ground truth: it
    executes the predicted SQL and reports what the engine said about it.
    """

    def __init__(self):
        super().__init__()
        
        self.evaluation_results = None

    def _run(self, state: SystemState):
        """
        Executes the evaluation process.
        
        Args:
            state (SystemState): The current system state.
        """

        self.evaluation_results = {}
        evaluation_keys = list(state.SQL_meta_infos.keys()) #+ list(state.errors.keys())
        
        for key in evaluation_keys:
            try:
                if key in state.SQL_meta_infos:
                    # checking only one of the SQLs
                    predicted_sql = state.SQL_meta_infos[key][0].SQL
                    evaluation_result = self._log_sql_result(state, predicted_sql)
                    
                elif key in state.errors:
                    evaluation_result = self._log_error(state.errors[key])
                    
            except Exception as e:
                predicted_sql = "--error--"
                Logger().log(
                    f"Node 'evaluation': {state.task.db_id}_{state.task.question_id}\n{type(e)}: {e}\n",
                    "error",
                )
                evaluation_result = {
                    "exec_res": "error",
                    "exec_err": str(e),
                }

            evaluation_result.update({
                "Question": state.task.question,
                "Evidence": state.task.evidence,
                "GOLD_SQL": state.task.SQL,
                "PREDICTED_SQL": predicted_sql
            })
            self.evaluation_results[key] = evaluation_result
            
        # Choosing the last SQL without syntax error as the final SQL
        # TODO: Implement a better way to choose the final SQL    
        final_result = None
        for key, evaluation_result in self.evaluation_results.items():
            if evaluation_result["exec_res"] not in ["incorrect answer", "--"]:
                final_result = evaluation_result
        self.evaluation_results["final_SQL"] = final_result
    
    def _log_sql_result(self, state: SystemState, SQL: str) -> Dict:
        """
        Executes the SQL query and logs its execution status.
        
        Args:
            state (SystemState): The current system state.
            SQL (str): The SQL query to execute.
            
        Returns:
            Dict[str, Any]: A dictionary containing the execution results.
        """
        
        database_manager = DatabaseManager()
        try:
            rows = database_manager.execute_sql(SQL, fetch=20)
        except Exception as e:
            Logger().log(
                f"Node 'evaluation': {state.task.db_id}_{state.task.question_id}\n{type(e)}: {e}\n",
                "error",
            )
            return {
                "exec_res": "error",
                "exec_err": str(e),
                "rows": [],
                "row_count": 0,
                "exec_status": "TIMEOUT" if isinstance(e, TimeoutError) else "SYNTACTICALLY_INCORRECT",
            }
        
        execution_status = database_manager.get_execution_status(SQL, execution_result=rows)
        result = {
            "exec_res": "completed",
            "exec_err": None,
            "rows": [list(row) for row in rows],
            "row_count": len(rows),
            "exec_status": execution_status.value,
        }
        
        return result
    
    def _log_error(self, error: str) -> Dict:
        """
        Log the error message.
        
        Args:
            error (str): The error message.
            
        Returns:
            Dict[str, Any]: A dictionary containing the evaluation results.
        """
        
        result = {
            "exec_res": "error",
            "exec_err": error,
        }
        
        return result
    
    def _get_updates(self, state: SystemState) -> Dict:
        return self.evaluation_results
