from ..LLMEnums import CoHereEnums, DocumentTypeEnums
import cohere
import logging
from src.paper_rag.helpers.config import get_settings, Settings


class CohereProvider:

    def __init__(
        self,
        max_input_tokens: int = 1000,
        max_output_tokens: int = 1000,
        temperature: float = 0.2,
    ):
        self.settings: Settings = get_settings()

        self.default_max_input_tokens = max_input_tokens
        self.default_max_output_tokens = max_output_tokens
        self.default_temperature = temperature

        self.client = cohere.AsyncClientV2(api_key=self.settings.COHERE_API_KEY)
        self.logger = logging.getLogger("uvicorn")

    async def embedding_text(self, text, document_type=None):

        input_type = CoHereEnums.DOCUMENT.value
        if document_type == DocumentTypeEnums.QUERY.value:
            input_type = CoHereEnums.QUERY.value

        if isinstance(text, str):
            text = [text]

        response = await self.client.embed(
            model=self.settings.EMBEDDING_MODEL_ID,
            texts=text,
            input_type=input_type,
            output_dimension=self.settings.EMBEDDING_SIZE,
        )

        if not response or not response.embeddings or not response.embeddings.float:
            self.logger.error("Error while embedding text with CoHere")
            return None

        return [f for f in response.embeddings.float]
