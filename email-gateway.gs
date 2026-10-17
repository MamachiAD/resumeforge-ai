// Free email sender for vendor notifications. Paste into script.google.com (signed in as the Gmail you want emails to come from).
// 1) Project Settings > Script properties > add SECRET = a long random text (same value as the worker secret EMAIL_SECRET).
// 2) Deploy > New deployment > Web app > Execute as: Me, Who has access: Anyone. Copy the Web app URL into the worker secret EMAIL_WEBHOOK.
// A free Gmail account can send roughly 100 emails a day (Google can change this).
function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  if (d.secret !== PropertiesService.getScriptProperties().getProperty('SECRET')) return ContentService.createTextOutput('denied');
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.to)) return ContentService.createTextOutput('bad address');
  MailApp.sendEmail({ to: d.to, subject: String(d.subject).slice(0, 150), body: String(d.text).slice(0, 4000), name: 'Mamachi Ads' });
  return ContentService.createTextOutput('ok');
}
