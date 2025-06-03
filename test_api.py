import requests
import json

# Configuration
BASE_URL = "http://localhost:5000/api/v1"

def test_health_check():
    """Test du health check"""
    response = requests.get(f"{BASE_URL}/health")
    print(f"Health Check: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print("-" * 50)

def test_auction_evaluation():
    """Test d'évaluation d'enchère"""
    # Test avec une enchère qui devrait matcher
    auction_data = {
        "item_id": "item_001",
        "category": "robe",
        "brand": "dior",
        "starting_price": 1500.0,
        "max_price": 2000.0,
        "auction_id": "auction_123"
    }
    
    response = requests.post(
        f"{BASE_URL}/auctions/evaluate",
        json=auction_data,
        headers={'Content-Type': 'application/json'}
    )
    
    print(f"Auction Evaluation (Success Expected): {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print("-" * 50)
    
    # Test avec une enchère qui ne devrait pas matcher
    auction_data_fail = {
        "item_id": "item_002",
        "category": "accessoire",  # Catégorie non supportée
        "brand": "hermes",         # Marque non supportée
        "starting_price": 500.0,
        "max_price": 800.0,
        "auction_id": "auction_124"
    }
    
    response = requests.post(
        f"{BASE_URL}/auctions/evaluate",
        json=auction_data_fail,
        headers={'Content-Type': 'application/json'}
    )
    
    print(f"Auction Evaluation (Rejection Expected): {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print("-" * 50)

def test_auction_result():
    """Test de résultat d'enchère"""
    result_data = {
        "auction_id": "auction_123",
        "item_id": "item_001",
        "won": True,
        "final_price": 1800.0
    }
    
    response = requests.post(
        f"{BASE_URL}/auctions/result",
        json=result_data,
        headers={'Content-Type': 'application/json'}
    )
    
    print(f"Auction Result: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print("-" * 50)

def test_user_preferences():
    """Test de récupération des préférences utilisateur"""
    response = requests.get(f"{BASE_URL}/users/1/preferences")
    
    print(f"User Preferences: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print("-" * 50)

if __name__ == "__main__":
    print("=== Tests de l'API Oktioneer ===\n")
    
    try:
        test_health_check()
        test_user_preferences()
        test_auction_evaluation()
        test_auction_result()
        
        print("✅ Tous les tests sont terminés!")
        
    except requests.exceptions.ConnectionError:
        print("❌ Erreur: Impossible de se connecter à l'API. Assurez-vous que le serveur est démarré.")
    except Exception as e:
        print(f"❌ Erreur inattendue: {str(e)}") 