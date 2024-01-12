from typing import (
    Optional,
    List,
    Union,
    Dict,
    Iterator,
    Any,
)

from llama_cpp import Llama
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletion,
    ChatCompletionChunk,
)
from openai.types.chat import ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChunkChoice
from openai.types.chat.chat_completion_chunk import ChoiceDelta
from openai.types.completion_usage import CompletionUsage

from api.adapter import get_prompt_adapter
from api.utils.compat import model_parse


class LlamaCppEngine:
    def __init__(
        self,
        model: Llama,
        model_name: str,
        prompt_name: Optional[str] = None,
    ):
        """
        Initializes a LlamaCppEngine instance.

        Args:
            model (Llama): The Llama model to be used by the engine.
            model_name (str): The name of the model.
            prompt_name (Optional[str], optional): The name of the prompt. Defaults to None.
        """
        self.model = model
        self.model_name = model_name.lower()
        self.prompt_name = prompt_name.lower() if prompt_name is not None else None
        self.prompt_adapter = get_prompt_adapter(self.model_name, prompt_name=self.prompt_name)

    def apply_chat_template(
        self,
        messages: List[ChatCompletionMessageParam],
        functions: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Applies a chat template to the given list of messages.

        Args:
            messages (List[ChatCompletionMessageParam]): The list of chat completion messages.
            functions (Optional[Union[Dict[str, Any], List[Dict[str, Any]]]], optional): The functions to be applied to the messages. Defaults to None.
            tools (Optional[List[Dict[str, Any]]], optional): The tools to be used for postprocessing the messages. Defaults to None.

        Returns:
            str: The chat template applied to the messages.
        """
        if self.prompt_adapter.function_call_available:
            messages = self.prompt_adapter.postprocess_messages(messages, functions, tools)
        return self.prompt_adapter.apply_chat_template(messages)

    def create_completion(self, prompt, **kwargs) -> Union[Iterator, Dict[str, Any]]:
        """
        Creates a completion using the specified prompt and additional keyword arguments.

        Args:
            prompt (str): The prompt for the completion.
            **kwargs: Additional keyword arguments to be passed to the model's create_completion method.

        Returns:
            Union[Iterator, Dict[str, Any]]: The completion generated by the model.
        """
        return self.model.create_completion(prompt, **kwargs)

    def _create_chat_completion(self, prompt, **kwargs) -> ChatCompletion:
        """
        Creates a chat completion using the specified prompt and additional keyword arguments.

        Args:
            prompt (str): The prompt for the chat completion.
            **kwargs: Additional keyword arguments to be passed to the create_completion method.

        Returns:
            ChatCompletion: The chat completion generated by the model.
        """
        completion = self.create_completion(prompt, **kwargs)
        message = ChatCompletionMessage(
            role="assistant",
            content=completion["choices"][0]["text"].strip(),
        )
        choice = Choice(
            index=0,
            message=message,
            finish_reason="stop",
            logprobs=None,
        )
        usage = model_parse(CompletionUsage, completion["usage"])
        return ChatCompletion(
            id="chat" + completion["id"],
            choices=[choice],
            created=completion["created"],
            model=completion["model"],
            object="chat.completion",
            usage=usage,
        )

    def _create_chat_completion_stream(self, prompt, **kwargs) -> Iterator:
        """
        Generates a stream of chat completion chunks based on the given prompt.

        Args:
            prompt (str): The prompt for generating chat completion chunks.
            **kwargs: Additional keyword arguments for creating completions.

        Yields:
            ChatCompletionChunk: A chunk of chat completion generated from the prompt.
        """
        completion = self.create_completion(prompt, **kwargs)
        for i, output in enumerate(completion):
            _id, _created, _model = output["id"], output["created"], output["model"]
            if i == 0:
                choice = ChunkChoice(
                    index=0,
                    delta=ChoiceDelta(role="assistant", content=""),
                    finish_reason=None,
                    logprobs=None,
                )
                yield ChatCompletionChunk(
                    id=f"chat{_id}",
                    choices=[choice],
                    created=_created,
                    model=_model,
                    object="chat.completion.chunk",
                )

            if output["choices"][0]["finish_reason"] is None:
                delta = ChoiceDelta(content=output["choices"][0]["text"])
            else:
                delta = ChoiceDelta()

            choice = ChunkChoice(
                index=0,
                delta=delta,
                finish_reason=output["choices"][0]["finish_reason"],
                logprobs=None,
            )
            yield ChatCompletionChunk(
                id=f"chat{_id}",
                choices=[choice],
                created=_created,
                model=_model,
                object="chat.completion.chunk",
            )

    def create_chat_completion(self, prompt, **kwargs) -> Union[Iterator, ChatCompletion]:
        return (
            self._create_chat_completion_stream(prompt, **kwargs)
            if kwargs.get("stream", False)
            else self._create_chat_completion(prompt, **kwargs)
        )

    @property
    def stop(self):
        """
        Gets the stop property of the prompt adapter.

        Returns:
            The stop property of the prompt adapter, or None if it does not exist.
        """
        return self.prompt_adapter.stop if hasattr(self.prompt_adapter, "stop") else None