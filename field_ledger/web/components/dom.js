// One helper the components share: an element with a class and some text.
export function el(tag, className, text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
