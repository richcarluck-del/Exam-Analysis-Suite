
import argparse
from app.database import SessionLocal
from app.models import LLMProvider, LLMModel
from app.security import decrypt_api_key, encrypt_api_key
from sqlalchemy.orm import Session

def show_api_key_for_model(model_id: int):
    db: Session = SessionLocal()
    try:
        model = db.query(LLMModel).filter(LLMModel.id == model_id).first()
        if not model:
            print(f"Error: Model with ID {model_id} not found.")
            return
        provider = model.provider
        if not provider:
            print(f"Error: Could not find a provider for model '{model.name}'.")
            return
        if not provider.encrypted_api_key:
            print(f"Info: Provider '{provider.name}' has no key stored.")
            return
        decrypted_key = decrypt_api_key(provider.encrypted_api_key)
        print("---")
        print(f"API Key for Provider: '{provider.name}' (model: '{model.name}')")
        print(f"Decrypted API Key: {decrypted_key}")
        print("---")
    finally:
        db.close()

def get_encrypted_key(plain_key: str):
    encrypted_key = encrypt_api_key(plain_key)
    print("---")
    print(f"Your new API key: {plain_key}")
    print(f"Encrypted version (copy this value into the database):\n{encrypted_key.decode('utf-8')}")
    print("---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage API keys for the GraphRAG application.")
    parser.add_argument("--show", type=int, metavar="MODEL_ID", help="Show the decrypted API key for the specified model ID.")
    parser.add_argument("--encrypt", type=str, metavar="'YOUR_API_KEY'", help="Encrypt a new API key to be stored in the database.")
    
    args = parser.parse_args()

    if args.show:
        show_api_key_for_model(args.show)
    elif args.encrypt:
        get_encrypted_key(args.encrypt)
    else:
        parser.print_help()
