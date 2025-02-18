
import logging
from typing import Literal

import torch
from sentence_transformers import SentenceTransformer
from FlagEmbedding import BGEM3FlagModel

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self, model_name) -> None:
        self.model_name = model_name
        self.model = None

    def get_model(self):
        if self.model is None:
            self.load_model()
        return self
    
    def close(self):
        if self.model:
            self.move_model_to_device("cpu")
        del self.model
    
    def load_model(self):
        raise NotImplementedError

    def move_model_to_device(self, device: Literal["cuda", "cpu"]):
        raise NotImplementedError
    
    def encode(self, text, batch_size):
        raise NotImplementedError


class ModelManagerStella(ModelManager):
    def load_model(self):
        if self.model is None:
            self.model = SentenceTransformer(self.model_name, trust_remote_code=True)
            logger.info("Loaded model")

    def move_model_to_device(self, device):
        if self.model.device != torch.device(device):
            logger.info(f"Moving model to {device}...")
            self.model = self.model.to(torch.device(device))
            logger.info(f"Model moved to {device}.")

    def encode(self, text, batch_size):
        return self.model.encode(text, batch_size=batch_size, prompt_name='s2s_query')


class ModelManagerFE(ModelManager):
    def load_model(self):
        if self.model is None:
            self.model = BGEM3FlagModel(self.model_name, use_fp16=True)      
            logger.info("Loaded model")

    def move_model_to_device(self, device):
        logger.info(f"Moving model to {device}...")
        if device == "cuda":
            self.model.model.cuda()
        else:
            self.model.model.cpu()
        logger.info(f"Model moved to {device}.")

    def encode(self, text, batch_size):
        logger.info("Vectorizing {} texts...".format(len(text)))
        return self.model.encode(text, batch_size=batch_size)["dense_vecs"]
    