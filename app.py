from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# Configuration
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///oktioneer.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enums
class ItemCategory(Enum):
    PANTALON = "pantalon"
    CHEMISE = "chemise"
    MANTEAU = "manteau"
    ROBE = "robe"
    JUPE = "jupe"
    PARKA = "parka"

class Brand(Enum):
    GUCCI = "gucci"
    SAINT_LAURENT = "saint_laurent"
    DIOR = "dior"
    LOUIS_VUITTON = "louis_vuitton"
    LANCEL = "lancel"

class EventType(Enum):
    BID_ACCEPTED = "bid_accepted"
    BID_REJECTED = "bid_rejected"
    BID_WON = "bid_won"
    BID_LOST = "bid_lost"

# Modèles de données
@dataclass
class AuctionProposal:
    item_id: str
    category: str
    brand: str
    starting_price: float
    max_price: float
    auction_id: str

@dataclass
class BidDecision:
    success: bool
    user_id: Optional[int] = None
    bid_amount: Optional[float] = None
    reason: Optional[str] = None

# Modèles SQLAlchemy
class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relation avec les préférences
    preferences = db.relationship('UserPreference', backref='user', lazy=True, cascade='all, delete-orphan')

class UserPreference(db.Model):
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    brand = db.Column(db.String(50), nullable=False)
    max_budget = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuctionEvent(db.Model):
    __tablename__ = 'auction_events'
    
    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(db.String(100), nullable=False)
    item_id = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    bid_amount = db.Column(db.Float, nullable=True)
    category = db.Column(db.String(50), nullable=False)
    brand = db.Column(db.String(50), nullable=False)
    starting_price = db.Column(db.Float, nullable=False)
    max_price = db.Column(db.Float, nullable=False)
    decision_reason = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Données supplémentaires en JSON - nom changé pour éviter le conflit
    extra_data = db.Column(db.Text, nullable=True)

# Services
class DecisionEngine:
    """Algorithme de décision pour les enchères"""
    
    @staticmethod
    def evaluate_auction(proposal: AuctionProposal) -> BidDecision:
        """
        Évalue une proposition d'enchère et retourne la décision optimale
        """
        try:
            # Récupération des préférences utilisateurs correspondantes
            matching_preferences = UserPreference.query.filter(
                UserPreference.category.ilike(f'%{proposal.category}%'),
                UserPreference.brand.ilike(f'%{proposal.brand}%'),
                UserPreference.max_budget >= proposal.starting_price,
                UserPreference.is_active == True
            ).all()
            
            if not matching_preferences:
                return BidDecision(
                    success=False,
                    reason="Aucun utilisateur ne correspond aux critères"
                )
            
            # Sélection de l'utilisateur avec le budget le plus élevé
            best_preference = max(matching_preferences, key=lambda p: p.max_budget)
            
            # Calcul du montant d'enchère optimal
            # Stratégie : enchérir au prix de départ + petite marge, sans dépasser le budget
            bid_amount = min(
                proposal.starting_price * 1.05,  # 5% au-dessus du prix de départ
                best_preference.max_budget
            )
            
            # Vérification que l'enchère ne dépasse pas le prix maximum
            if bid_amount > proposal.max_price:
                bid_amount = proposal.max_price
            
            return BidDecision(
                success=True,
                user_id=best_preference.user_id,
                bid_amount=round(bid_amount, 2),
                reason=f"Enchère optimale pour l'utilisateur {best_preference.user_id}"
            )
            
        except Exception as e:
            logger.error(f"Erreur lors de l'évaluation de l'enchère: {str(e)}")
            return BidDecision(
                success=False,
                reason=f"Erreur technique: {str(e)}"
            )

class DataWarehouseService:
    """Service de gestion du data warehouse (historisation)"""
    
    @staticmethod
    def store_auction_event(
        auction_id: str,
        item_id: str,
        proposal: AuctionProposal,
        decision: BidDecision,
        event_type: EventType
    ) -> bool:
        """
        Stocke un événement d'enchère dans le data warehouse
        """
        try:
            event = AuctionEvent(
                auction_id=auction_id,
                item_id=item_id,
                user_id=decision.user_id,
                event_type=event_type.value,
                bid_amount=decision.bid_amount,
                category=proposal.category,
                brand=proposal.brand,
                starting_price=proposal.starting_price,
                max_price=proposal.max_price,
                decision_reason=decision.reason,
                extra_data=json.dumps({
                    'proposal': asdict(proposal),
                    'decision': asdict(decision)
                })
            )
            
            db.session.add(event)
            db.session.commit()
            
            logger.info(f"Événement {event_type.value} enregistré pour auction_id: {auction_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement dans le data warehouse: {str(e)}")
            db.session.rollback()
            return False

# Routes API
@app.route('/api/v1/auctions/evaluate', methods=['POST'])
def evaluate_auction():
    """
    Endpoint principal pour évaluer une proposition d'enchère
    """
    try:
        # Validation du payload
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Payload JSON requis'}), 400
        
        required_fields = ['item_id', 'category', 'brand', 'starting_price', 'max_price', 'auction_id']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({'error': f'Champs manquants: {missing_fields}'}), 400
        
        # Création de la proposition
        proposal = AuctionProposal(
            item_id=data['item_id'],
            category=data['category'].lower(),
            brand=data['brand'].lower(),
            starting_price=float(data['starting_price']),
            max_price=float(data['max_price']),
            auction_id=data['auction_id']
        )
        
        # Évaluation par l'algorithme de décision
        decision = DecisionEngine.evaluate_auction(proposal)
        
        # Historisation de l'événement
        event_type = EventType.BID_ACCEPTED if decision.success else EventType.BID_REJECTED
        DataWarehouseService.store_auction_event(
            auction_id=proposal.auction_id,
            item_id=proposal.item_id,
            proposal=proposal,
            decision=decision,
            event_type=event_type
        )
        
        # Préparation de la réponse
        response = {
            'success': decision.success,
            'auction_id': proposal.auction_id,
            'item_id': proposal.item_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if decision.success:
            response.update({
                'user_id': decision.user_id,
                'bid_amount': decision.bid_amount,
                'message': decision.reason
            })
        else:
            response.update({
                'reason': decision.reason
            })
        
        status_code = 200 if decision.success else 422
        return jsonify(response), status_code
        
    except ValueError as e:
        logger.error(f"Erreur de validation: {str(e)}")
        return jsonify({'error': f'Données invalides: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500

@app.route('/api/v1/auctions/result', methods=['POST'])
def auction_result():
    """
    Endpoint pour recevoir le résultat d'une enchère (gagné/perdu)
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Payload JSON requis'}), 400
        
        required_fields = ['auction_id', 'item_id', 'won']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({'error': f'Champs manquants: {missing_fields}'}), 400
        
        # Récupération de l'événement d'enchère original
        original_event = AuctionEvent.query.filter_by(
            auction_id=data['auction_id'],
            item_id=data['item_id'],
            event_type=EventType.BID_ACCEPTED.value
        ).first()
        
        if not original_event:
            return jsonify({'error': 'Enchère originale non trouvée'}), 404
        
        # Enregistrement du résultat
        event_type = EventType.BID_WON if data['won'] else EventType.BID_LOST
        
        result_event = AuctionEvent(
            auction_id=data['auction_id'],
            item_id=data['item_id'],
            user_id=original_event.user_id,
            event_type=event_type.value,
            bid_amount=original_event.bid_amount,
            category=original_event.category,
            brand=original_event.brand,
            starting_price=original_event.starting_price,
            max_price=original_event.max_price,
            decision_reason=f"Enchère {'remportée' if data['won'] else 'perdue'}",
            extra_data=json.dumps({
                'won': data['won'],
                'final_price': data.get('final_price'),
                'winner_info': data.get('winner_info')
            })
        )
        
        db.session.add(result_event)
        db.session.commit()
        
        logger.info(f"Résultat d'enchère enregistré: {data['auction_id']} - {'Gagné' if data['won'] else 'Perdu'}")
        
        return jsonify({
            'success': True,
            'message': 'Résultat enregistré avec succès',
            'auction_id': data['auction_id'],
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du résultat: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Erreur interne du serveur'}), 500

# Routes utilitaires
@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0'
    }), 200

@app.route('/api/v1/users/<int:user_id>/preferences', methods=['GET'])
def get_user_preferences(user_id):
    """Récupération des préférences d'un utilisateur"""
    user = User.query.get_or_404(user_id)
    preferences = [
        {
            'id': pref.id,
            'category': pref.category,
            'brand': pref.brand,
            'max_budget': pref.max_budget,
            'is_active': pref.is_active
        }
        for pref in user.preferences if pref.is_active
    ]
    
    return jsonify({
        'user_id': user_id,
        'user_name': user.name,
        'preferences': preferences
    }), 200

# Initialisation de la base de données avec des données de test
def init_db():
    """Initialise la base de données avec des données de test"""
    with app.app_context():
        db.create_all()
        
        # Vérification si des données existent déjà
        if User.query.first():
            return
        
        # Création d'utilisateurs de test
        users_data = [
            {'name': 'Alice Martin', 'email': 'alice@example.com'},
            {'name': 'Bob Dubois', 'email': 'bob@example.com'},
            {'name': 'Claire Dupont', 'email': 'claire@example.com'},
        ]
        
        users = []
        for user_data in users_data:
            user = User(**user_data)
            db.session.add(user)
            users.append(user)
        
        db.session.commit()
        
        # Création de préférences de test
        preferences_data = [
            # Alice - Budget élevé, goûts luxury
            {'user_id': 1, 'category': 'robe', 'brand': 'dior', 'max_budget': 2500.0},
            {'user_id': 1, 'category': 'manteau', 'brand': 'gucci', 'max_budget': 3000.0},
            
            # Bob - Budget moyen, style décontracté
            {'user_id': 2, 'category': 'pantalon', 'brand': 'saint_laurent', 'max_budget': 800.0},
            {'user_id': 2, 'category': 'chemise', 'brand': 'gucci', 'max_budget': 600.0},
            
            # Claire - Accessoires, budget variable
            {'user_id': 3, 'category': 'jupe', 'brand': 'louis_vuitton', 'max_budget': 1200.0},
            {'user_id': 3, 'category': 'parka', 'brand': 'lancel', 'max_budget': 900.0},
        ]
        
        for pref_data in preferences_data:
            preference = UserPreference(**pref_data)
            db.session.add(preference)
        
        db.session.commit()
        logger.info("Base de données initialisée avec des données de test")

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000) 