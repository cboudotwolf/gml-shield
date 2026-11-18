export function setTextContent(target: HTMLElement, value: string): void {
  target.textContent = value;
}

export function createWarehouseCodeElement(warehouseCode: string): HTMLElement {
  const warehouseCodeElement = document.createElement("code");
  warehouseCodeElement.dataset.value = warehouseCode;
  warehouseCodeElement.textContent = "••••••••";
  return warehouseCodeElement;
}
