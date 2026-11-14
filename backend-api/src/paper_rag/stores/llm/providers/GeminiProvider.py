from ..LLMEnums import GeminiEnums
from google import genai
from google.genai import types
from src.paper_rag.helpers.config import get_settings, Settings
import logging


class GeminiProvider:

    def __init__(
        self,
        api_key,
        max_input_tokens: int = 1000,
        max_output_tokens: int = 1000,
        temperature: float = 0.2,
    ):
        self.settings: Settings = get_settings()
        self.api_key = api_key
        self.default_max_input_tokens = max_input_tokens
        self.default_max_output_tokens = max_output_tokens
        self.default_temperature = temperature

        self.client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        self.logger = logging.getLogger("uvicorn")

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = None,
        max_output_tokens: int = None,
        temperature: float = None,
    ):

        max_output_tokens = max_output_tokens or self.default_max_output_tokens
        temperature = temperature or self.default_temperature

        interaction = await self.client.aio.interactions.create(
            model=self.settings.GENERATION_MODEL_ID,
            system_instruction=system_prompt,
            input=[self.construct_prompt(prompt, role=GeminiEnums.USER.value)],
            generation_config=types.GenerationConfigDict(
                max_output_tokens=max_output_tokens, temperature=temperature, top_p=0.95
            ),
        )

        if not interaction or not interaction.output_text:
            self.logger.error("Error while generating text with Gemini")
            return None

        return interaction.output_text

    def construct_prompt(self, prompt, role):
        return {"type": role, "content": [{"type": "text", "text": prompt}]}
