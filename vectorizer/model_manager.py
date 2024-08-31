
import logging

import torch
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self):
        self.model = None

    def load_model(self):
        if self.model is None:
            self.model = SentenceTransformer("dunzhang/stella_en_1.5B_v5", trust_remote_code=True)
            self.model = self.model.to(torch.device('cpu'))
            logger.info("Model loaded on CPU.")

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

    def get_model(self):
        if self.model is None:
            self.load_model()
        return self.model
    
    def close(self):
        if self.model:
            self.move_model_to_cpu()
