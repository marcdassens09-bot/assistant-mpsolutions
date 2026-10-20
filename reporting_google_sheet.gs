// Script Google Apps Script du Google Sheet de reporting de la bulle.
// À coller dans le tableau : Extensions > Apps Script, puis Déployer >
// Nouveau déploiement > Application Web (exécuter en tant que : moi ;
// accès : tout le monde). L'URL obtenue, suivie de ?token=<JETON>, va dans
// la variable Render REPORTING_SHEET_URL.
// Le vrai jeton n'est jamais commité : ce dépôt est public.

const JETON = 'REMPLACER_PAR_LE_JETON';
const COLONNES = ['timestamp', 'question', 'profile', 'urgent', 'answered', 'client'];

function _reponse(objet) {
  return ContentService.createTextOutput(JSON.stringify(objet))
    .setMimeType(ContentService.MimeType.JSON);
}

function _feuille() {
  const feuille = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (feuille.getLastRow() === 0) {
    feuille.appendRow(COLONNES);
  }
  return feuille;
}

// Une question qui commence par = + - @ serait lue comme une formule.
function _texte(valeur) {
  const texte = String(valeur === undefined || valeur === null ? '' : valeur);
  return /^[=+\-@]/.test(texte) ? "'" + texte : texte;
}

function doPost(e) {
  if (!e || e.parameter.token !== JETON) {
    return _reponse({ ok: false });
  }
  const ev = JSON.parse(e.postData.contents);
  const verrou = LockService.getScriptLock();
  verrou.waitLock(10000);
  try {
    const feuille = _feuille();
    const plage = feuille.getRange(feuille.getLastRow() + 1, 1, 1, COLONNES.length);
    plage.setNumberFormat('@');
    plage.setValues([[
      _texte(ev.timestamp), _texte(ev.question), _texte(ev.profile || 'inconnu'),
      String(!!ev.urgent), String(ev.answered !== false), _texte(ev.client),
    ]]);
  } finally {
    verrou.releaseLock();
  }
  return _reponse({ ok: true });
}

function doGet(e) {
  if (!e || e.parameter.token !== JETON) {
    return _reponse({ ok: false });
  }
  const lignes = _feuille().getDataRange().getValues().slice(1);
  const events = lignes.map(function (l) {
    return {
      timestamp: l[0] instanceof Date ? l[0].toISOString() : String(l[0]),
      question: String(l[1]),
      profile: String(l[2] || 'inconnu'),
      urgent: String(l[3]).toLowerCase() === 'true',
      answered: String(l[4]).toLowerCase() !== 'false',
      client: String(l[5] || ''),
    };
  });
  return _reponse({ ok: true, events: events });
}
