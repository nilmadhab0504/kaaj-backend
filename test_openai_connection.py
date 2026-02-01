"""Test OpenAI API connection"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_openai_connection():
    api_key = os.environ.get("OPENAI_API_KEY")
    
    if not api_key:
        print("❌ OPENAI_API_KEY not found in environment")
        return False
    
    print(f"✓ API Key found: {api_key[:20]}...{api_key[-10:]}")
    
    try:
        from openai import OpenAI
        
        print("✓ OpenAI package imported successfully")
        
        # Initialize client
        client = OpenAI(api_key=api_key)
        print("✓ OpenAI client initialized")
        
        # Test with a simple completion
        print("\nTesting API connection with a simple request...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Connection successful!' if you can read this."}
            ],
            max_tokens=50,
            temperature=0
        )
        
        result = response.choices[0].message.content
        print(f"\n✅ OpenAI API Response: {result}")
        print(f"✅ Model used: {response.model}")
        print(f"✅ Tokens used: {response.usage.total_tokens}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import OpenAI: {e}")
        return False
    except Exception as e:
        print(f"❌ Error connecting to OpenAI: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing OpenAI API Connection")
    print("=" * 60)
    success = test_openai_connection()
    print("=" * 60)
    if success:
        print("✅ All tests passed! OpenAI is properly configured.")
    else:
        print("❌ Connection test failed. Please check your API key.")
    print("=" * 60)
