"""
Test script to verify the Pacifica Bot setup
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def test_environment():
    """Test if environment variables are loaded correctly"""
    load_dotenv()
    
    required_vars = [
        'AGENT_WALLET_PRIVATE_KEY',
        'MAIN_WALLET_PUBLIC_KEY',
        'API_ADDRESS',
        'WS_BASE_URL'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    logger.info("✅ All required environment variables are set")
    return True

def test_imports():
    """Test if all required packages can be imported"""
    try:
        import requests
        from solders.keypair import Keypair
        from src.pacifica_auth import PacificaAuth
        
        logger.info("✅ All required packages imported successfully")
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to import required packages: {e}")
        return False

if __name__ == "__main__":
    logger.info("🚀 Starting Pacifica Bot setup test...")
    
    env_ok = test_environment()
    imports_ok = test_imports()
    
    if env_ok and imports_ok:
        logger.info("✅ Setup test completed successfully!")
        logger.info("🎉 You're all set to run the Pacifica Bot!")
    else:
        logger.error("❌ Setup test failed. Please check the error messages above.")
        sys.exit(1)
