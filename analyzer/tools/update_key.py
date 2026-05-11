
import os
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import LLMModel, LLMProvider
from app.security import encrypt_api_key

def update_provider_key(model_id: int, new_plain_key: str):
    """
    Updates the API key for the provider associated with the given model ID.
    """
    db: Session = SessionLocal()
    try:
        model = db.query(LLMModel).filter(LLMModel.id == model_id).first()
        if not model:
            print(f"Error: Model with ID {model_id} not found.")
            return

        provider = model.provider
        if not provider:
            print(f"Error: No provider found for model '{model.name}'.")
            return

        print(f"Found provider '{provider.name}' associated with model '{model.name}'.")
        
        # Encrypt the new key
        new_encrypted_key = encrypt_api_key(new_plain_key)
        
        # Update the provider's key
        provider.encrypted_api_key = new_encrypted_key
        
        # Commit the session to save the changes to the database
        db.commit()
        
        print(f"Successfully updated the API key for provider '{provider.name}'.")

    except Exception as e:
        print(f"An error occurred: {e}")
        db.rollback()  # Roll back in case of error
    finally:
        db.close()

if __name__ == "__main__":
    # The model ID from the logs that had the auth error
    TARGET_MODEL_ID = 2
    # The new key you provided is now hardcoded here
    NEW_API_KEY = "sk-0ac4ae0c039846d889beae0b03c2a96b"
    
    print("Starting API key update process...")
    # Stop the FastAPI server before running this script if it's running
    # to avoid database lock issues.
    update_provider_key(TARGET_MODEL_ID, NEW_API_KEY)
    print("Update process finished.")
