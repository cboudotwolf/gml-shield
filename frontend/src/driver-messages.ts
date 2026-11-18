export interface DriverMessage {
  id: number;
  content: string;
  created_at: string;
}

/** Keep message markup as literal text so stored HTML cannot become executable DOM. */
export function createDriverMessageElement(driverMessage: DriverMessage): HTMLElement {
  const messageArticle = document.createElement("article");
  messageArticle.className = "driver-message";

  const messageText = document.createElement("p");
  messageText.textContent = driverMessage.content;

  const messageTimestamp = document.createElement("time");
  messageTimestamp.textContent = new Date(driverMessage.created_at).toLocaleString("fr-FR");

  messageArticle.append(messageText, messageTimestamp);
  return messageArticle;
}
