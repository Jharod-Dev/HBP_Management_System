from flask import Flask, render_template
from flask_mail import Mail
from flask_wtf import CSRFProtect

from .config import Config, validate_mail_config

csrf = CSRFProtect()
mail = Mail()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    validate_mail_config(app.config)
    csrf.init_app(app)
    mail.init_app(app)

    from .blueprints.admin import admin_bp
    from .blueprints.auth import auth_bp
    from .blueprints.customer import customer_bp
    from .blueprints.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        return render_template("errors/500.html"), 500

    return app
