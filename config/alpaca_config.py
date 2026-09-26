"""
Alpaca API Configuration
========================
Paper trading endpoint with user-provided API keys.

SECURITY WARNING: This file contains sensitive credentials.
In production, use environment variables or a secrets manager.
"""
import os

# Alpaca Paper Trading (fake money - safe for testing)
ALPACA_BASE_URL = "https://paper-api.alpaca.markets/v2"

# API Keys - stored as environment variables for safety
# Set these in your terminal:
#   export APCA_API_KEY_ID="YOUR_ALPACA_KEY_ID"
#   export APCA_API_SECRET_KEY="***"
ALPACA_API_KEY_ID = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_SECRET_KEY = os.environ.get("APCA_API_SECRET_KEY", "")

# For the current session, you can set them like this:
# os.environ["APCA_API_KEY_ID"] = "your_key_here"
# os.environ["APCA_API_SECRET_KEY"] = "your_secret_here"

def get_alpaca_credentials():
    """Get Alpaca API credentials from environment."""
    return {
        "APCA_API_KEY_ID": ALPACA_API_KEY_ID,
        "APCA_API_SECRET_KEY": ALPACA_SECRET_KEY,
        "base_url": ALPACA_BASE_URL,
    }

def verify_credentials():
    """Check if credentials are available."""
    missing = []
    if not ALPACA_API_KEY_ID:
        missing.append("APCA_API_KEY_ID")
    if not ALPACA_SECRET_KEY:
        missing.append("APCA_API_SECRET_KEY")
    
    if missing:
        return False, f"Missing environment variables: {', '.join(missing)}"
    return True, "Credentials configured successfully."

if __name__ == "__main__":
    ok, msg = verify_credentials()
    print(msg)
    if ok:
        print(f"Base URL: {ALPACA_BASE_URL}")
        # Show only first 8 chars of key for verification
        print(f"Key preview: {ALPACA_API_KEY_ID[:8]}... (length: {len(ALPACA_API_KEY_ID)})")
