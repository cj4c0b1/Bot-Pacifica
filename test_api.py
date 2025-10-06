"""
Test script to verify Pacifica API connectivity and authentication
"""
import os
import sys
import json
import logging
import requests
from dotenv import load_dotenv
from solders.keypair import Keypair
import base58

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def test_public_endpoints():
    """Test public API endpoints"""
    load_dotenv()
    base_url = os.getenv('API_ADDRESS', 'https://api.pacifica.fi/api/v1')
    
    # Test /info endpoint
    try:
        response = requests.get(f"{base_url}/info", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success') and 'data' in data:
                logger.info("✅ Successfully accessed /info endpoint")
                logger.info(f"Found {len(data['data'])} trading pairs")
                logger.info("Sample symbols: " + ", ".join([item['symbol'] for item in data['data'][:5]]) + "...")
                return True
            else:
                logger.error(f"❌ Unexpected response format from /info: {data}")
        else:
            logger.error(f"❌ Failed to access /info: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"❌ Error testing /info endpoint: {str(e)}")
    
    return False

def test_authentication():
    """Test authentication with Agent Wallet"""
    load_dotenv()
    
    # Get required environment variables
    agent_private_key = os.getenv('AGENT_WALLET_PRIVATE_KEY')
    main_public_key = os.getenv('MAIN_WALLET_PUBLIC_KEY')
    base_url = os.getenv('API_ADDRESS', 'https://api.pacifica.fi/api/v1')
    
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
        
        # Test account info endpoint (public)
        logger.info("\n🔍 Testing account info...")
        try:
            response = requests.get(
                f"{base_url}/account?account={main_public_key}",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    logger.info("✅ Successfully retrieved account info")
                    logger.info(f"Account Data: {json.dumps(data, indent=2)[:300]}...")
                    return True
                else:
                    logger.warning(f"⚠️  API returned success=false: {data.get('error')}")
            else:
                logger.warning(f"⚠️  Failed to get account info: {response.status_code} - {response.text}")
                
            # If we get here, the public endpoint didn't work, try authenticated
            logger.info("\n🔐 Trying authenticated endpoint...")
            
            # Prepare authentication headers (simplified)
            headers = {
                'Content-Type': 'application/json',
                'X-API-KEY': public_key,
            }
            
            # Try to get open orders
            response = requests.get(
                f"{base_url}/orders?account={main_public_key}",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    logger.info("✅ Successfully authenticated with the API")
                    logger.info(f"Open Orders: {json.dumps(data, indent=2)[:300]}...")
                    return True
                else:
                    logger.error(f"❌ API returned success=false: {data.get('error')}")
            else:
                logger.error(f"❌ Failed to authenticate: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"❌ Error during authentication test: {str(e)}")
            
    except Exception as e:
        logger.error(f"❌ Error initializing Keypair: {str(e)}")
    
    return False

if __name__ == "__main__":
    logger.info("🚀 Starting Pacifica API Test...")
    
    # Test public endpoints first
    logger.info("\n=== Testing Public Endpoints ===")
    public_success = test_public_endpoints()
    
    # Test authentication if public endpoints work
    auth_success = False
    if public_success:
        logger.info("\n=== Testing Authentication ===")
        auth_success = test_authentication()
    
    # Print summary
    logger.info("\n=== Test Summary ===")
    logger.info(f"Public API: {'✅' if public_success else '❌'}")
    logger.info(f"Authentication: {'✅' if auth_success else '❌'}")
    
    if public_success and not auth_success:
        logger.warning("\nℹ️  The API is reachable but authentication failed.")
        logger.warning("Please check your AGENT_WALLET_PRIVATE_KEY and MAIN_WALLET_PUBLIC_KEY in the .env file.")
    
    if not public_success:
        logger.error("\n❌ Failed to connect to the Pacifica API.")
        logger.error("Please check your internet connection and the API_ADDRESS in the .env file.")
    
    sys.exit(0 if public_success else 1)
