import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
from app import (
    app, db, User, UserPreference, AuctionEvent, 
    DecisionEngine, DataWarehouseService, AuctionProposal, 
    BidDecision, EventType, init_db
)
from config import TestingConfig

@pytest.fixture
def client():
    """Fixture pour le client de test Flask"""
    app.config.from_object(TestingConfig)
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

@pytest.fixture
def sample_users(client):
    """Fixture pour créer des utilisateurs de test"""
    with app.app_context():
        users = [
            User(name='Alice Martin', email='alice@test.com'),
            User(name='Bob Dubois', email='bob@test.com'),
            User(name='Claire Dupont', email='claire@test.com')
        ]
        
        for user in users:
            db.session.add(user)
        db.session.commit()
        
        # Ajout des préférences
        preferences = [
            UserPreference(user_id=1, category='robe', brand='dior', max_budget=2500.0),
            UserPreference(user_id=1, category='manteau', brand='gucci', max_budget=3000.0),
            UserPreference(user_id=2, category='pantalon', brand='saint_laurent', max_budget=800.0),
            UserPreference(user_id=3, category='jupe', brand='louis_vuitton', max_budget=1200.0, is_active=False)
        ]
        
        for pref in preferences:
            db.session.add(pref)
        db.session.commit()
        
        return users

class TestModels:
    """Tests pour les modèles de données"""
    
    def test_user_creation(self, client):
        """Test la création d'un utilisateur"""
        with app.app_context():
            user = User(name='Test User', email='test@example.com')
            db.session.add(user)
            db.session.commit()
            
            assert user.id is not None
            assert user.name == 'Test User'
            assert user.email == 'test@example.com'
            assert user.created_at is not None

    def test_user_preference_creation(self, client, sample_users):
        """Test la création d'une préférence utilisateur"""
        with app.app_context():
            preference = UserPreference(
                user_id=1,
                category='chemise',
                brand='gucci',
                max_budget=1000.0
            )
            db.session.add(preference)
            db.session.commit()
            
            assert preference.id is not None
            assert preference.user_id == 1
            assert preference.is_active == True
            assert preference.created_at is not None

    def test_auction_event_creation(self, client, sample_users):
        """Test la création d'un événement d'enchère"""
        with app.app_context():
            event = AuctionEvent(
                auction_id='auction_123',
                item_id='item_456',
                user_id=1,
                event_type='bid_accepted',
                bid_amount=1500.0,
                category='robe',
                brand='dior',
                starting_price=1200.0,
                max_price=2000.0,
                decision_reason='Enchère optimale'
            )
            db.session.add(event)
            db.session.commit()
            
            assert event.id is not None
            assert event.auction_id == 'auction_123'
            assert event.timestamp is not None

class TestDecisionEngine:
    """Tests pour l'algorithme de décision"""
    
    def test_evaluate_auction_success(self, client, sample_users):
        """Test d'évaluation d'enchère avec succès"""
        with app.app_context():
            proposal = AuctionProposal(
                item_id='item_123',
                category='robe',
                brand='dior',
                starting_price=2000.0,
                max_price=2800.0,
                auction_id='auction_123'
            )
            
            decision = DecisionEngine.evaluate_auction(proposal)
            
            assert decision.success == True
            assert decision.user_id == 1  # Alice avec budget de 2500
            assert decision.bid_amount == 2100.0  # 2000 * 1.05
            assert 'optimale' in decision.reason.lower()

    def test_evaluate_auction_no_matching_users(self, client, sample_users):
        """Test d'évaluation d'enchère sans utilisateurs correspondants"""
        with app.app_context():
            proposal = AuctionProposal(
                item_id='item_123',
                category='chaussures',  # Catégorie non existante
                brand='nike',           # Marque non existante
                starting_price=100.0,
                max_price=200.0,
                auction_id='auction_123'
            )
            
            decision = DecisionEngine.evaluate_auction(proposal)
            
            assert decision.success == False
            assert decision.user_id is None
            assert decision.bid_amount is None
            assert 'aucun utilisateur' in decision.reason.lower()

    def test_evaluate_auction_budget_exceeded(self, client, sample_users):
        """Test d'évaluation d'enchère avec budget dépassé"""
        with app.app_context():
            proposal = AuctionProposal(
                item_id='item_123',
                category='pantalon',
                brand='saint_laurent',
                starting_price=1000.0,  # Plus que le budget de Bob (800)
                max_price=1500.0,
                auction_id='auction_123'
            )
            
            decision = DecisionEngine.evaluate_auction(proposal)
            
            assert decision.success == False

    def test_evaluate_auction_bid_capped_by_max_price(self, client, sample_users):
        """Test que l'enchère est limitée par le prix maximum"""
        with app.app_context():
            proposal = AuctionProposal(
                item_id='item_123',
                category='robe',
                brand='dior',
                starting_price=2400.0,
                max_price=2450.0,  # Prix max inférieur à 2400 * 1.05 = 2520
                auction_id='auction_123'
            )
            
            decision = DecisionEngine.evaluate_auction(proposal)
            
            assert decision.success == True
            assert decision.bid_amount == 2450.0  # Limité par max_price

    @patch('app.logger')
    def test_evaluate_auction_exception_handling(self, mock_logger, client):
        """Test de gestion d'exception dans l'évaluation d'enchère"""
        with app.app_context():
            # Simulation d'une erreur en passant des données invalides
            with patch('app.UserPreference.query') as mock_query:
                mock_query.filter.side_effect = Exception("Database error")
                
                proposal = AuctionProposal(
                    item_id='item_123',
                    category='robe',
                    brand='dior',
                    starting_price=2000.0,
                    max_price=2800.0,
                    auction_id='auction_123'
                )
                
                decision = DecisionEngine.evaluate_auction(proposal)
                
                assert decision.success == False
                assert 'erreur technique' in decision.reason.lower()
                mock_logger.error.assert_called()

class TestDataWarehouseService:
    """Tests pour le service de data warehouse"""
    
    def test_store_auction_event_success(self, client, sample_users):
        """Test de stockage d'événement avec succès"""
        with app.app_context():
            proposal = AuctionProposal(
                item_id='item_123',
                category='robe',
                brand='dior',
                starting_price=2000.0,
                max_price=2800.0,
                auction_id='auction_123'
            )
            
            decision = BidDecision(
                success=True,
                user_id=1,
                bid_amount=2100.0,
                reason='Test decision'
            )
            
            result = DataWarehouseService.store_auction_event(
                auction_id='auction_123',
                item_id='item_123',
                proposal=proposal,
                decision=decision,
                event_type=EventType.BID_ACCEPTED
            )
            
            assert result == True
            
            # Vérification que l'événement a été créé
            event = AuctionEvent.query.filter_by(auction_id='auction_123').first()
            assert event is not None
            assert event.event_type == 'bid_accepted'
            assert event.user_id == 1

    @patch('app.logger')
    def test_store_auction_event_failure(self, mock_logger, client):
        """Test de gestion d'erreur lors du stockage"""
        with app.app_context():
            with patch('app.db.session.commit') as mock_commit:
                mock_commit.side_effect = Exception("Database error")
                
                proposal = AuctionProposal(
                    item_id='item_123',
                    category='robe',
                    brand='dior',
                    starting_price=2000.0,
                    max_price=2800.0,
                    auction_id='auction_123'
                )
                
                decision = BidDecision(success=True, user_id=1, bid_amount=2100.0)
                
                result = DataWarehouseService.store_auction_event(
                    auction_id='auction_123',
                    item_id='item_123',
                    proposal=proposal,
                    decision=decision,
                    event_type=EventType.BID_ACCEPTED
                )
                
                assert result == False
                mock_logger.error.assert_called()

class TestAPIEndpoints:
    """Tests pour les endpoints API"""
    
    def test_health_check(self, client):
        """Test du endpoint health check"""
        response = client.get('/api/v1/health')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert 'timestamp' in data
        assert data['version'] == '1.0.0'

    def test_evaluate_auction_success(self, client, sample_users):
        """Test d'évaluation d'enchère via API avec succès"""
        payload = {
            'item_id': 'item_123',
            'category': 'robe',
            'brand': 'dior',
            'starting_price': 2000.0,
            'max_price': 2800.0,
            'auction_id': 'auction_123'
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['user_id'] == 1
        assert data['bid_amount'] == 2100.0
        assert data['auction_id'] == 'auction_123'

    def test_evaluate_auction_no_match(self, client, sample_users):
        """Test d'évaluation d'enchère sans correspondance"""
        payload = {
            'item_id': 'item_123',
            'category': 'chaussures',
            'brand': 'nike',
            'starting_price': 100.0,
            'max_price': 200.0,
            'auction_id': 'auction_123'
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 422
        data = json.loads(response.data)
        assert data['success'] == False
        assert 'reason' in data

    def test_evaluate_auction_missing_fields(self, client):
        """Test d'évaluation d'enchère avec champs manquants"""
        payload = {
            'item_id': 'item_123',
            'category': 'robe'
            # Champs manquants: brand, starting_price, max_price, auction_id
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'champs manquants' in data['error'].lower()

    def test_evaluate_auction_no_payload(self, client):
        """Test d'évaluation d'enchère sans payload"""
        response = client.post('/api/v1/auctions/evaluate',
                             content_type='application/json')
        
        # Flask retourne 500 quand request.get_json() est appelé sans données
        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data

    def test_evaluate_auction_invalid_data(self, client, sample_users):
        """Test d'évaluation d'enchère avec données invalides"""
        payload = {
            'item_id': 'item_123',
            'category': 'robe',
            'brand': 'dior',
            'starting_price': 'invalid_price',  # Prix invalide
            'max_price': 2800.0,
            'auction_id': 'auction_123'
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'données invalides' in data['error'].lower()

    def test_auction_result_success(self, client, sample_users):
        """Test d'enregistrement de résultat d'enchère avec succès"""
        # D'abord, créer un événement d'enchère acceptée
        with app.app_context():
            event = AuctionEvent(
                auction_id='auction_123',
                item_id='item_456',
                user_id=1,
                event_type='bid_accepted',
                bid_amount=2100.0,
                category='robe',
                brand='dior',
                starting_price=2000.0,
                max_price=2800.0
            )
            db.session.add(event)
            db.session.commit()
        
        payload = {
            'auction_id': 'auction_123',
            'item_id': 'item_456',
            'won': True,
            'final_price': 2200.0
        }
        
        response = client.post('/api/v1/auctions/result',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['auction_id'] == 'auction_123'

    def test_auction_result_not_found(self, client):
        """Test d'enregistrement de résultat pour enchère inexistante"""
        payload = {
            'auction_id': 'nonexistent_auction',
            'item_id': 'nonexistent_item',
            'won': True
        }
        
        response = client.post('/api/v1/auctions/result',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'enchère originale non trouvée' in data['error'].lower()

    def test_auction_result_missing_fields(self, client):
        """Test d'enregistrement de résultat avec champs manquants"""
        payload = {
            'auction_id': 'auction_123'
            # Champs manquants: item_id, won
        }
        
        response = client.post('/api/v1/auctions/result',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'champs manquants' in data['error'].lower()

    def test_get_user_preferences_success(self, client, sample_users):
        """Test de récupération des préférences utilisateur avec succès"""
        response = client.get('/api/v1/users/1/preferences')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['user_id'] == 1
        assert data['user_name'] == 'Alice Martin'
        assert len(data['preferences']) == 2  # Alice a 2 préférences actives

    def test_get_user_preferences_not_found(self, client):
        """Test de récupération des préférences pour utilisateur inexistant"""
        response = client.get('/api/v1/users/999/preferences')
        
        assert response.status_code == 404

    def test_get_user_preferences_only_active(self, client, sample_users):
        """Test que seules les préférences actives sont retournées"""
        response = client.get('/api/v1/users/3/preferences')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['preferences']) == 0  # Claire n'a qu'une préférence inactive

class TestDatabaseInitialization:
    """Tests pour l'initialisation de la base de données"""
    
    def test_init_db_creates_tables(self, client):
        """Test que init_db crée les tables"""
        with app.app_context():
            # Supprimer les tables existantes
            db.drop_all()
            
            # Appeler init_db
            init_db()
            
            # Vérifier que les tables existent et contiennent des données
            users = User.query.all()
            preferences = UserPreference.query.all()
            
            assert len(users) == 3
            assert len(preferences) == 6
            assert users[0].name == 'Alice Martin'

    def test_init_db_skips_if_data_exists(self, client, sample_users):
        """Test que init_db ne recrée pas les données si elles existent"""
        with app.app_context():
            # Compter les utilisateurs existants
            initial_count = User.query.count()
            
            # Appeler init_db
            init_db()
            
            # Vérifier que le nombre n'a pas changé
            final_count = User.query.count()
            assert final_count == initial_count

class TestEdgeCases:
    """Tests pour les cas limites"""
    
    def test_case_insensitive_matching(self, client, sample_users):
        """Test que la correspondance est insensible à la casse"""
        payload = {
            'item_id': 'item_123',
            'category': 'ROBE',  # Majuscules
            'brand': 'DIOR',     # Majuscules
            'starting_price': 2000.0,
            'max_price': 2800.0,
            'auction_id': 'auction_123'
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] == True

    def test_multiple_users_same_budget(self, client):
        """Test de sélection quand plusieurs utilisateurs ont le même budget"""
        # Stockage des IDs pour éviter le problème de session détachée
        user_ids = []
        
        with app.app_context():
            # Créer deux utilisateurs avec le même budget
            user1 = User(name='User 1', email='user1@test.com')
            user2 = User(name='User 2', email='user2@test.com')
            db.session.add_all([user1, user2])
            db.session.commit()
            
            # Stocker les IDs avant que les objets ne soient détachés
            user_ids = [user1.id, user2.id]
            
            pref1 = UserPreference(user_id=user1.id, category='robe', brand='dior', max_budget=2500.0)
            pref2 = UserPreference(user_id=user2.id, category='robe', brand='dior', max_budget=2500.0)
            db.session.add_all([pref1, pref2])
            db.session.commit()
        
        payload = {
            'item_id': 'item_123',
            'category': 'robe',
            'brand': 'dior',
            'starting_price': 2000.0,
            'max_price': 2800.0,
            'auction_id': 'auction_123'
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] == True
        # L'un des deux utilisateurs devrait être sélectionné
        assert data['user_id'] in user_ids

    def test_bid_amount_precision(self, client, sample_users):
        """Test de la précision du montant d'enchère"""
        payload = {
            'item_id': 'item_123',
            'category': 'pantalon',
            'brand': 'saint_laurent',
            'starting_price': 750.33,  # Prix avec décimales
            'max_price': 800.0,
            'auction_id': 'auction_123'
        }
        
        response = client.post('/api/v1/auctions/evaluate',
                             json=payload,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        # Vérifier que le montant est arrondi à 2 décimales
        expected_bid = round(750.33 * 1.05, 2)
        assert data['bid_amount'] == expected_bid

if __name__ == '__main__':
    pytest.main(['-v', '--cov=app', '--cov-report=html']) 