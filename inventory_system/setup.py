#!/usr/bin/env python3
"""
BotBruz Inventory Management System Setup Script
This script helps set up the application for first-time use.
"""

import os
import sys
import subprocess
import mysql.connector
from mysql.connector import Error
import bcrypt
from config import Config

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 8):
        print("❌ Error: Python 3.8 or higher is required")
        print(f"Current version: {sys.version}")
        return False
    print(f"✅ Python version: {sys.version.split()[0]}")
    return True

def install_dependencies():
    """Install required Python packages"""
    print("📦 Installing Python dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing dependencies: {e}")
        return False

def create_env_file():
    """Create .env file from template"""
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            print("📝 Creating .env file from template...")
            
            # Get database credentials
            print("\n🔧 Database Configuration:")
            db_host = input("MySQL Host (default: localhost): ") or "localhost"
            db_user = input("MySQL Username (default: root): ") or "root"
            db_password = input("MySQL Password: ")
            
            # Read template and replace values
            with open('.env.example', 'r') as f:
                content = f.read()
            
            content = content.replace('your_mysql_password', db_password)
            content = content.replace('localhost', db_host)
            content = content.replace('root', db_user)
            
            # Generate a random secret key
            import secrets
            secret_key = secrets.token_urlsafe(32)
            content = content.replace('your-secret-key-change-this-in-production', secret_key)
            
            with open('.env', 'w') as f:
                f.write(content)
            
            print("✅ .env file created successfully")
            return db_host, db_user, db_password
        else:
            print("❌ .env.example file not found")
            return None, None, None
    else:
        print("✅ .env file already exists")
        return None, None, None

def setup_database(host, user, password):
    """Set up the database"""
    if not all([host, user, password]):
        print("⚠️  Skipping database setup (credentials not provided)")
        return True
    
    print("🗄️  Setting up database...")
    try:
        # Connect to MySQL
        connection = mysql.connector.connect(
            host=host,
            user=user,
            password=password
        )
        
        cursor = connection.cursor()
        
        # Read and execute SQL schema
        if os.path.exists('database_schema.sql'):
            with open('database_schema.sql', 'r') as f:
                sql_script = f.read()
            
            # Split and execute each statement
            statements = sql_script.split(';')
            for statement in statements:
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            
            connection.commit()
            print("✅ Database setup completed")
            
        else:
            print("❌ database_schema.sql file not found")
            return False
        
        cursor.close()
        connection.close()
        return True
        
    except Error as e:
        print(f"❌ Database setup error: {e}")
        return False

def create_admin_user():
    """Create additional admin user if needed"""
    print("\n👤 Admin User Setup:")
    create_new = input("Do you want to create a new admin user? (y/n): ").lower().strip()
    
    if create_new == 'y':
        from config import Config
        config = Config()
        
        try:
            connection = mysql.connector.connect(**config.DB_CONFIG)
            cursor = connection.cursor()
            
            username = input("Enter new admin username: ").strip()
            password = input("Enter new admin password: ").strip()
            email = input("Enter admin email (optional): ").strip()
            
            if not username or not password:
                print("❌ Username and password are required")
                return False
            
            # Hash password
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Insert new admin user
            cursor.execute(
                "INSERT INTO admin_users (username, password, email) VALUES (%s, %s, %s)",
                (username, hashed_password, email if email else None)
            )
            connection.commit()
            
            print(f"✅ Admin user '{username}' created successfully")
            cursor.close()
            connection.close()
            return True
            
        except Error as e:
            print(f"❌ Error creating admin user: {e}")
            return False
    
    print("✅ Using default admin user (username: admin, password: admin123)")
    return True

def verify_installation():
    """Verify that everything is set up correctly"""
    print("\n🔍 Verifying installation...")
    
    # Check if all required files exist
    required_files = [
        'app.py',
        'config.py',
        'requirements.txt',
        'database_schema.sql',
        '.env'
    ]
    
    missing_files = []
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    if missing_files:
        print(f"❌ Missing files: {', '.join(missing_files)}")
        return False
    
    # Check if templates directory exists
    if not os.path.exists('templates'):
        print("❌ Templates directory not found")
        return False
    
    # Check template files
    template_files = [
        'templates/base.html',
        'templates/login.html',
        'templates/dashboard.html',
        'templates/add_components.html',
        'templates/inventory.html',
        'templates/edit_component.html'
    ]
    
    missing_templates = []
    for template in template_files:
        if not os.path.exists(template):
            missing_templates.append(template)
    
    if missing_templates:
        print(f"❌ Missing templates: {', '.join(missing_templates)}")
        return False
    
    print("✅ All required files are present")
    
    # Test database connection
    try:
        from config import Config
        config = Config()
        connection = mysql.connector.connect(**config.DB_CONFIG)
        
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM components")
        cursor.execute("SELECT COUNT(*) FROM admin_users")
        
        cursor.close()
        connection.close()
        print("✅ Database connection successful")
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    
    return True

def main():
    """Main setup function"""
    print("🚀 BotBruz Inventory Management System Setup")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Install dependencies
    if not install_dependencies():
        return False
    
    # Create .env file and get database credentials
    db_host, db_user, db_password = create_env_file()
    
    # Set up database
    if not setup_database(db_host, db_user, db_password):
        print("⚠️  Database setup failed. You may need to run database_schema.sql manually.")
    
    # Create admin user
    create_admin_user()
    
    # Verify installation
    if verify_installation():
        print("\n🎉 Setup completed successfully!")
        print("\nNext steps:")
        print("1. Run the application: python app.py")
        print("2. Open your browser to: http://localhost:5000")
        print("3. Login with: admin / admin123")
        print("\n📚 Read README.md for more information")
        return True
    else:
        print("\n❌ Setup completed with errors. Please check the messages above.")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during setup: {e}")
        sys.exit(1)