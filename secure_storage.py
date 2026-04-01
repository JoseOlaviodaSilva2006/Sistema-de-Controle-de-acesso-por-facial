import cv2
import numpy as np
import os
from pathlib import Path
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger("AuraSecureStorage")

class SecureStorage:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.key = None
        self.fernet = None
        self._load_key()

    def _load_key(self):
        key_path = Path(".env.key")
        if not key_path.exists():
            logger.warning("Chave de criptografia não encontrada! Gerando nova chave...")
            key = Fernet.generate_key()
            with open(key_path, "wb") as f:
                f.write(key)
        
        with open(key_path, "rb") as f:
            self.key = f.read().strip()
            self.fernet = Fernet(self.key)

    def save_encrypted_image(self, img_array, filepath: str, quality=85):
        """Codifica a imagem em memória (JPEG) e salva o binário encriptado em disco."""
        try:
            # Codifica imagem para buffer jpeg
            ret, buffer = cv2.imencode('.jpg', img_array, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ret:
                raise ValueError("Falha ao encodar imagem para memória.")
            
            # Criptografa os bytes da imagem
            encrypted_data = self.fernet.encrypt(buffer.tobytes())
            
            # Garante a extensão `.enc` para segurança
            safe_path = str(filepath)
            if safe_path.endswith('.jpg'):
                safe_path += '.enc'
            
            with open(safe_path, "wb") as f:
                f.write(encrypted_data)
                
            return safe_path
        except Exception as e:
            logger.error(f"Erro ao salvar imagem encriptada {filepath}: {e}")
            raise

    def load_decrypted_image(self, filepath: str, flags=cv2.IMREAD_COLOR):
        """Lê um arquivo encriptado, desencripta e decodifica para array numpy na memória RAM."""
        try:
            with open(filepath, "rb") as f:
                encrypted_data = f.read()
            
            # Desencripta
            decrypted_bytes = self.fernet.decrypt(encrypted_data)
            
            # Transforma em array numpy do cv2
            nparr = np.frombuffer(decrypted_bytes, np.uint8)
            img = cv2.imdecode(nparr, flags)
            
            if img is None:
                raise ValueError("Decodificação da imagem falhou.")
            return img
        except Exception as e:
            logger.error(f"Erro ao ler imagem encriptada {filepath}: {e}")
            return None

# Instância Singleton
secure_io = SecureStorage.get_instance()
