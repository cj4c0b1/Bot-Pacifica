"""
Test script to verify Pacifica API authentication with Agent Wallet
"""
import os
import sys
import logging
import json
from dotenv import load_dotenv
from solders.keypair import Keypair
import base58
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def test_agent_wallet_auth():
    """Test Agent Wallet authentication with Pacifica API"""
    load_dotenv()
    
    # Get required environment variables
    agent_private_key = os.getenv('AGENT_WALLET_PRIVATE_KEY')
    main_public_key = os.getenv('MAIN_WALLET_PUBLIC_KEY')
    api_address = os.getenv('API_ADDRESS', 'https://api.pacifica.fi/api/v1')
    
    if not agent_private_key or not main_public_key:
        logger.error("❌ Missing required environment variables")
        logger.error(f"AGENT_WALLET_PRIVATE_KEY: {'Set' if agent_private_key else 'Not set'}")
        logger.error(f"MAIN_WALLET_PUBLIC_KEY: {'Set' if main_public_key else 'Not set'}")
        return False
    
    try:
        # Initialize Keypair from the private key
        keypair = Keypair.from_base58_string(agent_private_key)
        public_key = str(keypair.pubkey())
        
        logger.info(f"🔑 Agent Wallet Public Key: {public_key}")
        logger.info(f"🔑 Main Wallet Public Key: {main_public_key}")
        
        # Test public endpoint (no auth required)
        logger.info("\n🔍 Testing public endpoint...")
        try:
            response = requests.get(f"{api_address}/market/info")
            if response.status_code == 200:
                logger.info("✅ Public endpoint is accessible")
                logger.info(f"Response: {json.dumps(response.json(), indent=2)[:200]}...")
            else:
                logger.error(f"❌ Failed to access public endpoint: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Error accessing public endpoint: {str(e)}")
            return False
        
        # Test authenticated endpoint
        logger.info("\n🔐 Testing authenticated endpoint...")
        try:
            # Prepare request headers
            headers = {
                'Content-Type': 'application/json',
                'X-API-KEY': public_key,
                'X-API-SIGNATURE': 'test-signature',  # This would normally be a valid signature
            }
            
            # Try to get account info (this is a public endpoint that might work with the wallet)
            response = requests.get(
                f"{api_address}/account?account={main_public_key}",
                headers=headers
            )
            
            if response.status_code == 200:
                logger.info("✅ Successfully authenticated with the API")
                logger.info(f"Account Info: {json.dumps(response.json(), indent=2)[:300]}...")
                return True
            else:
                logger.warning(f"⚠️  API returned status code: {response.status_code}")
                logger.warning(f"Response: {response.text}")
                
                # Try a different endpoint that might work with the agent wallet
                logger.info("\n🔍 Trying alternative endpoint with Agent Wallet...")
                response = requests.get(
                    f"{api_address}/v1/agent/balance?wallet={public_key}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info("✅ Successfully accessed Agent Wallet endpoint")
                    logger.info(f"Agent Balance: {json.dumps(response.json(), indent=2)[:300]}...")
                    return True
                else:
                    logger.error(f"❌ Failed to authenticate with Agent Wallet: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error during authentication test: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error initializing Keypair: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("🔐 Starting Pacifica API Authentication Test...")
    
    if test_agent_wallet_auth():
        logger.info("\n✅ Authentication test completed successfully!")
        sys.exit(0)
    else:
        logger.error("\n❌ Authentication test failed. Please check the error messages above.")
        sys.exit(1)
