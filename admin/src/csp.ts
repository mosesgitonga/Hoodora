// Every <style> element the page creates gets this page's nonce (decision D.5).
//
// Ant Design passes the nonce on its own styles, but a few helpers underneath it
// can't: a dialog's scroll lock, the scrollbar measurement. Under the CSP those
// were blocked (the page behind a dialog still scrolled). Only the app's own
// scripts create elements, and they can read the nonce from the page anyway, so
// tagging what they create doesn't widen the policy: the nonce still keeps out
// injected markup, which never gets one.

export function tagCreatedStyles(nonce: string | undefined, doc: Document = document): void {
  if (!nonce) return;
  const create = doc.createElement.bind(doc);
  doc.createElement = ((tagName: string, options?: ElementCreationOptions) => {
    const element = create(tagName, options);
    if (tagName.toLowerCase() === "style") (element as HTMLStyleElement).nonce = nonce;
    return element;
  }) as Document["createElement"];
}
