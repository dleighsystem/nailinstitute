"""
NAIL Institute - Base Agent Class
===================================
Common agent abstraction used across all experiments.
Wraps OllamaLLM with identity, memory, and logging.
"""

from typing import Optional
from .ollama_llm import OllamaLLM, LLMResponse
from .logger import ExperimentLogger


class Agent:
    """
    A named agent with a system prompt, backed by a local Ollama model.
    Tracks conversation history and token usage.
    """

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        model: str,
        logger: Optional[ExperimentLogger] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        llm_instance=None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        if llm_instance is not None:
            # Use externally provided LLM (multi-provider support)
            self.llm = llm_instance
        else:
            # Default: Ollama (backward compatible)
            self.llm = OllamaLLM(
                model=model,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        self.logger = logger
        self.history: list[dict] = []
        self.total_tokens_used = 0

    def respond(self, message: str, json_mode: bool = False) -> str:
        """
        Send a message to this agent and get a response.
        Maintains conversation history.
        """
        self.history.append({"role": "user", "content": message})

        resp: LLMResponse = self.llm.chat(
            messages=self.history,
            json_mode=json_mode,
        )

        self.history.append({"role": "assistant", "content": resp.content})
        self.total_tokens_used += resp.total_tokens

        if self.logger:
            self.logger.log_agent_turn(
                agent=self.name,
                prompt=message,
                response=resp.content,
                tokens=resp.total_tokens,
                throughput={
                    "tokens_per_second": resp.tokens_per_second,
                    "prompt_eval_time_s": resp.prompt_eval_time_s,
                    "generation_time_s": resp.generation_time_s,
                    "time_to_first_token_s": resp.time_to_first_token_s,
                    "wall_clock_s": resp.elapsed_seconds,
                },
            )

        return resp.content

    def respond_stateless(self, message: str, json_mode: bool = False) -> str:
        """
        Single-turn response without history accumulation.
        Useful for one-off evaluations.
        """
        resp: LLMResponse = self.llm.generate(message, json_mode=json_mode)
        self.total_tokens_used += resp.total_tokens

        if self.logger:
            self.logger.log_agent_turn(
                agent=self.name,
                prompt=message,
                response=resp.content,
                tokens=resp.total_tokens,
                throughput={
                    "tokens_per_second": resp.tokens_per_second,
                    "prompt_eval_time_s": resp.prompt_eval_time_s,
                    "generation_time_s": resp.generation_time_s,
                    "time_to_first_token_s": resp.time_to_first_token_s,
                    "wall_clock_s": resp.elapsed_seconds,
                },
            )
        return resp.content

    def reset_history(self):
        """Clear conversation history."""
        self.history = []

    def get_stats(self) -> dict:
        """Return comprehensive agent-level stats including throughput."""
        llm_stats = self.llm.get_usage_stats()
        return {
            "agent": self.name,
            "role": self.role,
            "model": self.llm.model,
            "total_tokens_used": self.total_tokens_used,
            "history_length": len(self.history),
            **llm_stats,
        }
