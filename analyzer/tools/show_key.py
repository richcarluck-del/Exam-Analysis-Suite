
from app.database import SessionLocal
from app.models import LLMProvider, LLMModel
from app.security import decrypt_api_key
from sqlalchemy.orm import Session

def show_api_key_for_model(model_id: int):
    """
    Connects to the database, finds the provider for the given model ID,
    decrypts its API key, and prints it.
    """
    db: Session = SessionLocal()
    try:
        # Find the model by its ID
        model = db.query(LLMModel).filter(LLMModel.id == model_id).first()
        if not model:
            print(f"Error: Model with ID {model_id} not found.")
            return

        # Get the associated provider
        provider = model.provider
        if not provider:
            print(f"Error: Could not find a provider associated with model '{model.name}'.")
            return

        if not provider.encrypted_api_key:
            print(f"Info: Provider '{provider.name}' does not have an API key stored in the database.")
            return

        # Decrypt and print the key
        decrypted_key = decrypt_api_key(provider.encrypted_api_key)
        
        print("---")
        print(f"API Key found for Provider: '{provider.name}' (used by model: '{model.name}')")
        print(f"Decrypted API Key: {decrypted_key}")
        print("---")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    # From your logs, the ingestion was for model_id: 2
    target_model_id = 2
    show_api_key_for_model(target_model_id)
