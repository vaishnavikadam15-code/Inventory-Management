import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this-in-production'
    
    # Database settings
    DB_HOST = os.environ.get('DB_HOST') or 'localhost'
    DB_NAME = os.environ.get('DB_NAME') or 'botbruz_inventory'
    DB_USER = os.environ.get('DB_USER') or 'root'
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or 'Root@123'  # Change this to your actual MySQL password
    
    @property
    def DB_CONFIG(self):
        return {
            'host': self.DB_HOST,
            'database': self.DB_NAME,
            'user': self.DB_USER,
            'password': self.DB_PASSWORD
        }
# # Flask Configuration
# SECRET_KEY=your-secret-key-change-this-in-production

# # Database Configuration
# DB_HOST=localhost
# DB_NAME=botbruz_inventory
# DB_USER=root
# DB_PASSWORD=your_mysql_password

# # Application Settings
# FLASK_ENV=development
# FLASK_DEBUG=True