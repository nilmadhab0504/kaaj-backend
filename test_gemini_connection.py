"""Test Google Gemini API connection"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_gemini_connection():
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        print("❌ GEMINI_API_KEY not found in environment")
        return False
    
    print(f"✓ API Key found: {api_key[:15]}...{api_key[-10:]}")
    
    try:
        import google.generativeai as genai
        
        print("✓ Google Generative AI package imported successfully")
        
        # Configure API key
        genai.configure(api_key=api_key)
        print("✓ Gemini API configured")
        
        # Test with a simple completion
        print("\nTesting API connection with a simple request...")
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            "Say 'Connection successful!' if you can read this.",
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=50,
            )
        )
        
        result = response.text
        print(f"\n✅ Gemini API Response: {result}")
        print(f"✅ Model used: gemini-1.5-flash")
        
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import Google Generative AI: {e}")
        return False
    except Exception as e:
        print(f"❌ Error connecting to Gemini: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Google Gemini API Connection")
    print("=" * 60)
    success = test_gemini_connection()
    print("=" * 60)
    if success:
        print("✅ All tests passed! Gemini is properly configured.")
    else:
        print("❌ Connection test failed. Please check your API key.")
    print("=" * 60)
