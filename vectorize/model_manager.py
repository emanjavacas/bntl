
import logging

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
    
    def load_model(self):
        raise NotImplementedError

    def move_model_to_cpu(self):
        raise NotImplementedError
    
    def move_model_to_gpu(self):
        raise NotImplementedError
    
    def close(self):
        if self.model:
            self.move_model_to_cpu()
        del self.model

    def encode(self, text, batch_size):
        return self.model.encode(text, batch_size=batch_size)


class ModelManagerStella(ModelManager):
    def load_model(self):
        if self.model is None:
            self.model = SentenceTransformer(self.model_name, trust_remote_code=True)
            logger.info("Loaded model")
            self.move_model_to_cpu()

    def move_model_to_gpu(self):
        if self.model.device != torch.device('cuda'):
            logger.info("Moving model to GPU...")
            self.model = self.model.to(torch.device('cuda'))
            logger.info("Model moved to GPU.")

    def move_model_to_cpu(self):
        if self.model.device != torch.device('cpu'):
            logger.info("Moving model back to CPU...")
            self.model = self.model.to(torch.device('cpu'))
            logger.info("Model moved back to CPU.")

    def encode(self, text, batch_size):
        return self.model.encode(text, batch_size=batch_size, prompt_name='s2s_query')


class ModelManagerFE(ModelManager):
    def load_model(self):
        if self.model is None:
            self.model = BGEM3FlagModel(self.model_name, use_fp16=True)      
            logger.info("Loaded model")  
            self.move_model_to_cpu()

    def move_model_to_gpu(self):
        logger.info("Moving model to GPU...")
        self.model.model.cuda()
        logger.info("Model moved to GPU.")

    def move_model_to_cpu(self):
        logger.info("Moving model back to CPU...")
        self.model.model.cpu()
        logger.info("Model moved back to CPU.")

    def encode(self, text, batch_size):
        logger.info("Vectorizing {} texts...".format(len(text)))
        return self.model.encode(text, batch_size=batch_size)["dense_vecs"]
    