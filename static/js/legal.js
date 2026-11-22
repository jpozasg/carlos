// /impressum: the page's own labels and the footer in the app's four languages. The operator's imprint text is shown
// as written (it comes from the data directory); without a language file the English text in the page stays.
import { load, initialLang, t } from './i18n.js';

const $ = id => document.getElementById(id);
function paint() {
  document.title = t('imprint_title') + ' · Carlos';
  $('imp-title').textContent = t('imprint_title');
  if ($('imp-missing')) $('imp-missing').textContent = t('imprint_missing');
  $('f-src').textContent = t('source_code');
  $('f-priv').textContent = t('footer_privacy');
}
load(initialLang()).then(paint, () => {});
