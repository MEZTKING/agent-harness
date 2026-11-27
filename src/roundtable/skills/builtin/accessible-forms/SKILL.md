---
name: Accessible forms
when: Building web forms, sign-up or settings pages that everyone can use.
tags: [html, layout, kind:website, kind:web-app]
---
- Every input has a visible `<label for=...>`; a placeholder is not a label.
- Group related choices with `<fieldset>` and `<legend>` (radio buttons, an address).
- Use the right input type (`email`, `tel`, `number`, `date`) and `autocomplete` values so phones and browsers help.
- Mark required fields in words as well as with `required`; don't rely on colour alone.
- Show an error next to its field, in words that say how to fix it, and link it with `aria-describedby`. Move focus to the first error after a failed submit.
- Everything works with the keyboard alone: a sensible tab order, a visible focus outline, buttons that are real `<button>` elements.
- Text and its background have a contrast of at least 4.5 to 1; touch targets are at least 44 pixels.
- Don't clear what someone typed when the form is sent back with an error.
- Check it once with the keyboard only and once with the page zoomed to 200 %.
