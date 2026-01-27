"""Keycloak Admin API utilities."""
import httpx
import os
import sqlite3
from typing import Optional, Tuple
from src.config import settings


class KeycloakAdmin:
    """Keycloak admin client for managing clients."""
    
    def __init__(self):
        self.base_url = None
        self.realm = "streamlink"
        self.admin_user = "admin"
        self.admin_password = ""
        self._access_token: Optional[str] = None
    
    def _get_keycloak_config(self):
        """Get Keycloak configuration from services table.
        
        In SQLite mode, Keycloak cannot be deployed, so use fallback.
        In Postgres mode, read from services table.
        """
        if self.base_url:
            return  # Already loaded
        
        try:
            from src.database import get_database_url
            db_url = get_database_url()
            
            if "postgresql" in db_url.lower():
                # Read from Postgres services table
                import asyncio
                from src.database import AsyncSessionLocal
                from sqlalchemy import select
                import json
                
                async def fetch_from_services():
                    async with AsyncSessionLocal() as session:
                        from src.models.service import Service
                        stmt = select(Service).where(
                            Service.manifest_name == "keycloak",
                            Service.is_active == True
                        )
                        result = await session.execute(stmt)
                        keycloak_service = result.scalar_one_or_none()
                        
                        if keycloak_service and keycloak_service.config:
                            config = json.loads(keycloak_service.config)
                            return config.get("external_url"), config.get("admin_password")
                    return None, None
                
                # Run async function
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import nest_asyncio
                        nest_asyncio.apply()
                    url, encrypted_password = loop.run_until_complete(fetch_from_services())
                except RuntimeError:
                    url, encrypted_password = asyncio.run(fetch_from_services())
                
                if url:
                    self.base_url = url
                    if encrypted_password:
                        from src.utils.crypto import get_crypto_service
                        crypto = get_crypto_service()
                        self.admin_password = crypto.decrypt(encrypted_password)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to load Keycloak config from services table: {e}")
        
        # Fallback to localhost if not configured
        if not self.base_url:
            self.base_url = f"http://localhost:{settings.KEYCLOAK_NODEPORT}"
    
    async def _get_admin_token(self) -> str:
        """Get admin access token, always fetch fresh to avoid expiration."""
        self._get_keycloak_config()
        token_url = f"{self.base_url}/realms/master/protocol/openid-connect/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": self.admin_user,
                    "password": self.admin_password,
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to get admin token: {response.text}")
            
            return response.json()["access_token"]
    
    async def realm_exists(self, realm_name: str) -> bool:
        """Check if a realm exists."""
        token = await self._get_admin_token()
        url = f"{self.base_url}/admin/realms/{realm_name}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            return response.status_code == 200
    
    async def create_realm(self, realm_name: str, display_name: str = None) -> bool:
        """Create a new realm."""
        if await self.realm_exists(realm_name):
            return True
        
        token = await self._get_admin_token()
        url = f"{self.base_url}/admin/realms"
        
        realm_data = {
            "realm": realm_name,
            "displayName": display_name or realm_name,
            "enabled": True,
            "sslRequired": "none",
            "registrationAllowed": False,
            "loginWithEmailAllowed": True,
            "duplicateEmailsAllowed": False,
            "resetPasswordAllowed": True,
            "editUsernameAllowed": False,
            "bruteForceProtected": True
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=realm_data
            )
            
            if response.status_code not in [201, 409]:
                raise Exception(f"Failed to create realm: {response.text}")
            
            return True
    
    async def client_exists(self, client_id: str) -> bool:
        """Check if a client exists in the realm."""
        token = await self._get_admin_token()
        url = f"{self.base_url}/admin/realms/{self.realm}/clients"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"clientId": client_id}
            )
            
            if response.status_code != 200:
                return False
            
            clients = response.json()
            return len(clients) > 0
    
    async def get_client_uuid(self, client_id: str) -> Optional[str]:
        """Get the UUID of a client by client_id."""
        token = await self._get_admin_token()
        url = f"{self.base_url}/admin/realms/{self.realm}/clients"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"clientId": client_id}
            )
            
            if response.status_code != 200:
                return None
            
            clients = response.json()
            if len(clients) > 0:
                return clients[0]["id"]
            return None
    
    async def create_client(
        self, 
        client_id: str, 
        redirect_uris: list[str],
        description: str = ""
    ) -> Tuple[str, str]:
        """
        Create a new confidential client and return (client_id, client_secret).
        
        Args:
            client_id: The client ID
            redirect_uris: List of valid redirect URIs
            description: Optional client description
            
        Returns:
            Tuple of (client_id, client_secret)
        """
        # Check if client already exists
        if await self.client_exists(client_id):
            # Get existing secret
            secret = await self.get_client_secret(client_id)
            return (client_id, secret)
        
        token = await self._get_admin_token()
        url = f"{self.base_url}/admin/realms/{self.realm}/clients"
        
        client_data = {
            "clientId": client_id,
            "name": client_id,
            "description": description,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": False,
            "redirectUris": redirect_uris,
            "webOrigins": ["+"],  # Allow CORS from redirect URIs
            "attributes": {
                "access.token.lifespan": "900"
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=client_data
            )
            
            if response.status_code not in [201, 409]:
                raise Exception(f"Failed to create client: {response.text}")
        
        # Get the client secret
        secret = await self.get_client_secret(client_id)
        return (client_id, secret)
    
    async def get_client_secret(self, client_id: str) -> str:
        """Get the secret for a client."""
        token = await self._get_admin_token()
        uuid = await self.get_client_uuid(client_id)
        
        if not uuid:
            raise Exception(f"Client {client_id} not found")
        
        url = f"{self.base_url}/admin/realms/{self.realm}/clients/{uuid}/client-secret"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to get client secret: {response.text}")
            
            return response.json()["value"]
    
    async def delete_client(self, client_id: str) -> bool:
        """
        Delete a client from the realm.
        
        Args:
            client_id: The client ID to delete
            
        Returns:
            True if deleted, False if client didn't exist
        """
        token = await self._get_admin_token()
        uuid = await self.get_client_uuid(client_id)
        
        if not uuid:
            return False
        
        url = f"{self.base_url}/admin/realms/{self.realm}/clients/{uuid}"
        
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code not in [204, 404]:
                raise Exception(f"Failed to delete client: {response.text}")
            
            return response.status_code == 204


# Singleton instance
keycloak_admin = KeycloakAdmin()
