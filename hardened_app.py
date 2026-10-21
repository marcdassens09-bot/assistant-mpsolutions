import os
import website_app as secured


class SiteSecurityError(Exception):
    """Erreur de sécurité volontairement distincte de ValueError.

    Cela garantit que le blocage explicite d'une IP privée dans le premier
    filtre ne peut pas être absorbé par le except ValueError utilisé pour
    distinguer un nom de domaine d'une adresse IP.
    """


secured.SiteSecurityError = SiteSecurityError
app = secured.app

import retell_webhook  # noqa: E402,F401  (ajoute la route /retell-webhook)
import demo_vocale  # noqa: E402,F401  (ajoute la page cachée /demo-vocale/<code>)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
