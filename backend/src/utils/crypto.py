"""Encryption utilities for sensitive data."""
import os
import base64
from cryptography.fernet import Fernet


class CryptoService:
    """Service for encrypting and decrypting sensitive data."""
    
    def __init__(self):
        """Initialize crypto service with encryption key from environment."""
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            raise ValueError("ENCRYPTION_KEY environment variable is not set")
        
        # Ensure the key is properly formatted for Fernet
        try:
            self.cipher = Fernet(encryption_key.encode())
        except Exception as e:
            raise ValueError(f"Invalid ENCRYPTION_KEY format: {e}")
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string and return base64-encoded ciphertext."""
        if not plaintext:
            return plaintext
        
        encrypted_bytes = self.cipher.encrypt(plaintext.encode())
        return base64.b64encode(encrypted_bytes).decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext and return plaintext."""
        if not ciphertext:
            return ciphertext
        
        try:
            encrypted_bytes = base64.b64decode(ciphertext.encode())
            decrypted_bytes = self.cipher.decrypt(encrypted_bytes)
            return decrypted_bytes.decode()
        except Exception as e:
            raise ValueError(f"Failed to decrypt data: {e}")


# Singleton instance
_crypto_service = None


def get_crypto_service() -> CryptoService:
    """Get or create the crypto service singleton."""
    global _crypto_service
    if _crypto_service is None:
        _crypto_service = CryptoService()
    return _crypto_service
