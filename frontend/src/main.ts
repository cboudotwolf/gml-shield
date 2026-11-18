import "./style.css";
import "./driver-messages.css";

import { requestApi } from "./api-client";
import { createDriverMessageElement, type DriverMessage } from "./driver-messages";
import { createWarehouseCodeElement, setTextContent } from "./dom-utils";

type UserRole = "ADMIN" | "DISPATCHER" | "DRIVER";

interface User {
  id: number;
  email: string;
  role: UserRole;
}

interface Mission {
  id: number;
  title: string;
  destination: string;
  secret_code: string;
  status: string;
  driver_id: number;
  documents: string[];
}

interface Driver {
  id: number;
  email: string;
  role: string;
}

interface AuditEntry {
  action: string;
  resource: string;
  result: string;
  created_at: string;
}

const applicationRoot = (() => {
  const rootElement = document.querySelector<HTMLElement>("#app");
  if (!rootElement) throw new Error("Le conteneur de l'application est introuvable.");
  return rootElement;
})();

let driverNotificationSocket: WebSocket | undefined;

function createElement<TagName extends keyof HTMLElementTagNameMap>(
  tagName: TagName,
  className?: string,
  textContent?: string,
): HTMLElementTagNameMap[TagName] {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (textContent !== undefined) element.textContent = textContent;
  return element;
}

function createFieldLabel(labelText: string, formControl: HTMLElement): HTMLLabelElement {
  const fieldLabel = createElement("label");
  fieldLabel.append(document.createTextNode(labelText), formControl);
  return fieldLabel;
}

function createButton(label: string, className?: string): HTMLButtonElement {
  const button = createElement("button", className, label);
  button.type = "button";
  return button;
}

function setFeedback(messageText: string, isError = false): void {
  const feedbackElement = applicationRoot.querySelector<HTMLElement>("#message");
  if (!feedbackElement) return;
  setTextContent(feedbackElement, messageText);
  feedbackElement.className = isError ? "message error" : "message";
}

function createApplicationHeader(email: string, statusLabel?: string): HTMLElement {
  const header = createElement("header", "topbar");
  const brand = createElement("div");
  brand.append(createElement("span", "brand-mark small", "G"), createElement("strong", undefined, "GML-SHIELD"));

  const account = createElement("div", "account");
  account.append(document.createTextNode(email));
  if (statusLabel) account.append(createElement("span", "live-dot", statusLabel));
  account.append(createButton("Déconnexion", "text-button"));
  header.append(brand, account);
  return header;
}

function renderLogin(): void {
  const loginSection = createElement("section", "login-card");
  loginSection.append(
    createElement("div", "brand-mark", "G"),
    createElement("p", "eyebrow", "GML · ESPACE SÉCURISÉ"),
    createElement("h1", undefined, "GML-SHIELD"),
    createElement("p", "muted", "Connectez-vous pour accéder à vos missions."),
  );

  const loginForm = createElement("form");
  loginForm.id = "login-form";
  loginForm.append(
    createFieldLabel("Adresse e-mail", Object.assign(createElement("input"), {
      name: "email",
      type: "email",
      autocomplete: "username",
      required: true,
    })),
    createFieldLabel("Mot de passe", Object.assign(createElement("input"), {
      name: "password",
      type: "password",
      autocomplete: "current-password",
      minLength: 14,
      required: true,
    })),
  );
  const submitButton = createButton("Se connecter");
  submitButton.type = "submit";
  loginForm.append(submitButton);
  loginForm.addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    const submittedForm = submitEvent.currentTarget as HTMLFormElement;
    const submittedValues = new FormData(submittedForm);
    try {
      await requestApi("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: submittedValues.get("email"),
          password: submittedValues.get("password"),
        }),
      });
      await loadApplication();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Connexion impossible", true);
    }
  });

  loginSection.append(loginForm, createElement("p", "message"));
  loginSection.lastElementChild?.setAttribute("id", "message");
  applicationRoot.replaceChildren(loginSection);
}

function createMissionCard(mission: Mission, isDriver: boolean): HTMLElement {
  const missionCard = createElement("article", "mission");
  const missionHeading = createElement("div", "mission-top");
  const statusClass = mission.status.toLowerCase().replace(/[^a-z0-9_-]/g, "");
  missionHeading.append(
    createElement("span", `status ${statusClass}`, mission.status),
    createElement("span", "muted", `Mission #${mission.id}`),
  );
  missionCard.append(
    missionHeading,
    createElement("h3", undefined, mission.title),
  );

  const destination = createElement("p");
  destination.append(createElement("strong", undefined, "Destination"), document.createElement("br"));
  destination.append(document.createTextNode(mission.destination));
  missionCard.append(destination);

  if (isDriver) {
    missionCard.append(createWarehouseCodeDisplay(mission.secret_code));
  }

  const missionActions = createElement("div", "mission-actions");
  if (isDriver) {
    addDriverMissionActions(mission, missionCard, missionActions);
  } else {
    addDispatcherMissionActions(mission, missionActions);
  }
  missionCard.append(missionActions);
  return missionCard;
}

function createWarehouseCodeDisplay(warehouseCode: string): HTMLElement {
  const secretDisplay = createElement("div", "secret");
  const codeLabel = createElement("span", undefined, "Code entrepôt");
  const warehouseCodeElement = createWarehouseCodeElement(warehouseCode);
  const revealButton = createButton("Afficher", "text-button");
  revealButton.addEventListener("click", () => {
    const codeIsVisible = warehouseCodeElement.textContent !== "••••••••";
    setTextContent(
      warehouseCodeElement,
      codeIsVisible ? "••••••••" : warehouseCodeElement.dataset.value ?? "",
    );
    revealButton.textContent = codeIsVisible ? "Afficher" : "Masquer";
  });
  secretDisplay.append(codeLabel, warehouseCodeElement, revealButton);
  return secretDisplay;
}

function addDriverMissionActions(
  mission: Mission,
  missionCard: HTMLElement,
  missionActions: HTMLElement,
): void {
  if (mission.status === "IN_PROGRESS") {
    const uploadLabel = createElement("label", "upload-button", "Ajouter une preuve");
    const uploadInput = createElement("input");
    uploadInput.type = "file";
    uploadInput.accept = "image/jpeg,image/png,application/pdf";
    uploadInput.addEventListener("change", async () => {
      const uploadedFile = uploadInput.files?.[0];
      if (!uploadedFile) return;
      const uploadBody = new FormData();
      uploadBody.append("upload", uploadedFile);
      try {
        await requestApi(`/api/missions/${mission.id}/documents`, {
          method: "POST",
          body: uploadBody,
        });
        await loadApplication();
        setFeedback("Preuve envoyée et contrôlée.");
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : "Envoi impossible", true);
      }
    });
    uploadLabel.append(uploadInput);
    missionActions.append(uploadLabel);
  }

  const nextStatus = mission.status === "PENDING"
    ? "IN_PROGRESS"
    : mission.status === "IN_PROGRESS" && mission.documents.length > 0
      ? "COMPLETED"
      : undefined;
  if (!nextStatus) return;

  const actionLabel = nextStatus === "IN_PROGRESS" ? "Commencer la mission" : "Clôturer la mission";
  const statusButton = createButton(actionLabel, "secondary");
  statusButton.addEventListener("click", async () => {
    try {
      await requestApi(`/api/missions/${mission.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus }),
      });
      await loadApplication();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Mise à jour impossible", true);
    }
  });
  missionActions.append(statusButton);
  missionCard.setAttribute("aria-label", `Mission ${mission.id}`);
}

function addDispatcherMissionActions(mission: Mission, missionActions: HTMLElement): void {
  const firstDocumentId = mission.documents[0];
  if (!firstDocumentId) return;

  const downloadButton = createButton("Télécharger la preuve", "secondary");
  downloadButton.addEventListener("click", async () => {
    const missionPath = encodeURIComponent(String(mission.id));
    const documentPath = encodeURIComponent(firstDocumentId);
    try {
      const response = await fetch(
        `/api/missions/${missionPath}/documents/${documentPath}`,
        { credentials: "same-origin" },
      );
      if (!response.ok) throw new Error(`Erreur ${response.status}`);
      const downloadBlob = await response.blob();
      const downloadLink = document.createElement("a");
      const downloadUrl = URL.createObjectURL(downloadBlob);
      downloadLink.href = downloadUrl;
      downloadLink.download = "preuve";
      downloadLink.click();
      URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Téléchargement impossible", true);
    }
  });
  missionActions.append(downloadButton);
}

async function showDispatcherDashboard(user: User): Promise<void> {
  const [missions, drivers] = await Promise.all([
    requestApi<Mission[]>("/api/missions"),
    requestApi<Driver[]>("/api/drivers"),
  ]);
  const content = createElement("section", "content");
  content.append(
    createElement("p", "eyebrow", "ESPACE RÉPARTITEUR"),
    createElement("h1", undefined, "Suivi des missions"),
  );
  const columns = createElement("div", "columns");
  const missionFormPanel = createElement("section", "panel");
  missionFormPanel.append(createElement("h2", undefined, "Créer une mission"));
  const missionForm = createElement("form");
  missionForm.id = "mission-form";

  const titleInput = createElement("input");
  titleInput.name = "title";
  titleInput.maxLength = 120;
  titleInput.required = true;
  const destinationInput = createElement("input");
  destinationInput.name = "destination";
  destinationInput.maxLength = 500;
  destinationInput.required = true;
  const warehouseCodeInput = createElement("input");
  warehouseCodeInput.name = "secret_code";
  warehouseCodeInput.maxLength = 200;
  warehouseCodeInput.required = true;
  const driverSelect = createElement("select");
  driverSelect.name = "driver_id";
  driverSelect.required = true;
  for (const driver of drivers) {
    const driverOption = createElement("option", undefined, driver.email);
    driverOption.value = String(driver.id);
    driverSelect.append(driverOption);
  }
  missionForm.append(
    createFieldLabel("Intitulé", titleInput),
    createFieldLabel("Destination", destinationInput),
    createFieldLabel("Code entrepôt", warehouseCodeInput),
    createFieldLabel("Chauffeur", driverSelect),
  );
  const createMissionButton = createButton("Créer la mission");
  createMissionButton.type = "submit";
  missionForm.append(createMissionButton);
  missionForm.addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    const submittedValues = new FormData(submitEvent.currentTarget as HTMLFormElement);
    try {
      await requestApi("/api/missions", {
        method: "POST",
        body: JSON.stringify({
          title: submittedValues.get("title"),
          destination: submittedValues.get("destination"),
          secret_code: submittedValues.get("secret_code"),
          driver_id: Number(submittedValues.get("driver_id")),
        }),
      });
      await showDispatcherDashboard(user);
      setFeedback("Mission créée et transmise au chauffeur.");
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Création impossible", true);
    }
  });
  missionFormPanel.append(missionForm, createElement("p", "message"));
  missionFormPanel.lastElementChild?.setAttribute("id", "message");

  const missionsPanel = createElement("section");
  missionsPanel.append(createElement("h2", undefined, "Missions créées"));
  const missionList = createElement("div", "mission-list");
  if (missions.length === 0) {
    missionList.append(createElement("p", "muted", "Aucune mission."));
  } else {
    for (const mission of missions) missionList.append(createMissionCard(mission, false));
  }
  missionsPanel.append(missionList);
  columns.append(missionFormPanel, missionsPanel);
  content.append(columns);
  applicationRoot.replaceChildren(createApplicationHeader(user.email), content);
}

async function showDriverDashboard(user: User): Promise<void> {
  const [missions, driverMessages] = await Promise.all([
    requestApi<Mission[]>("/api/missions"),
    requestApi<DriverMessage[]>("/api/messages"),
  ]);
  const content = createElement("section", "content narrow");
  content.append(
    createElement("p", "eyebrow", "ESPACE CHAUFFEUR"),
    createElement("h1", undefined, "Mes missions"),
    createElement("p", "muted", "Vos missions restent accessibles après une interruption réseau."),
  );

  const missionList = createElement("div", "mission-list");
  missionList.id = "mission-list";
  if (missions.length === 0) {
    missionList.append(createElement("div", "empty", "Aucune mission assignée."));
  } else {
    for (const mission of missions) missionList.append(createMissionCard(mission, true));
  }

  const messagesPanel = createElement("section", "panel driver-message-panel");
  messagesPanel.append(createElement("h2", undefined, "Mes messages"));
  const messageForm = createElement("form");
  messageForm.id = "driver-message-form";
  const messageInput = createElement("textarea");
  messageInput.name = "content";
  messageInput.rows = 4;
  messageInput.maxLength = 2000;
  messageInput.required = true;
  messageForm.append(createFieldLabel("Écrire un message", messageInput));
  const saveMessageButton = createButton("Enregistrer le message");
  saveMessageButton.type = "submit";
  messageForm.append(saveMessageButton);
  messageForm.addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    const submittedValues = new FormData(submitEvent.currentTarget as HTMLFormElement);
    const messageContent = String(submittedValues.get("content") ?? "");
    try {
      await requestApi("/api/messages", {
        method: "POST",
        body: JSON.stringify({ content: messageContent }),
      });
      await showDriverDashboard(user);
      setFeedback("Message enregistré.");
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Enregistrement impossible", true);
    }
  });

  const messageList = createElement("div", "driver-message-list");
  if (driverMessages.length === 0) {
    messageList.append(createElement("p", "muted", "Aucun message enregistré."));
  } else {
    for (const driverMessage of driverMessages) {
      messageList.append(createDriverMessageElement(driverMessage));
    }
  }
  messagesPanel.append(messageForm, messageList);
  content.append(missionList, messagesPanel, createElement("p", "message"));
  content.lastElementChild?.setAttribute("id", "message");

  driverNotificationSocket?.close();
  const websocketProtocol = location.protocol === "https:" ? "wss:" : "ws:";
  driverNotificationSocket = new WebSocket(`${websocketProtocol}//${location.host}/api/ws`);
  driverNotificationSocket.addEventListener("message", async (socketMessage) => {
    let notification: unknown;
    try {
      notification = JSON.parse(socketMessage.data);
    } catch {
      return;
    }
    if (
      notification
      && typeof notification === "object"
      && "event" in notification
      && notification.event === "NEW_MISSION"
    ) {
      await showDriverDashboard(user);
      setFeedback("Une nouvelle mission vous a été assignée.");
    }
  });
  applicationRoot.replaceChildren(createApplicationHeader(user.email, "Temps réel"), content);
}

async function showSecurityDashboard(user: User): Promise<void> {
  const auditEntries = await requestApi<AuditEntry[]>("/api/audit");
  const content = createElement("section", "content");
  content.append(
    createElement("p", "eyebrow", "ADMINISTRATION DE SÉCURITÉ"),
    createElement("h1", undefined, "Journal d’audit"),
  );
  const auditPanel = createElement("section", "panel audit-list");
  for (const auditEntry of auditEntries) {
    const auditRow = createElement("div", "audit-row");
    auditRow.append(
      createElement("span", undefined, auditEntry.action),
      createElement("span", undefined, auditEntry.resource),
      createElement("span", "status", auditEntry.result),
      createElement("time", undefined, new Date(auditEntry.created_at).toLocaleString("fr-FR")),
    );
    auditPanel.append(auditRow);
  }
  if (auditEntries.length === 0) auditPanel.append(createElement("p", "muted", "Aucune trace."));
  content.append(auditPanel);
  applicationRoot.replaceChildren(createApplicationHeader(user.email), content);
}

async function loadApplication(): Promise<void> {
  driverNotificationSocket?.close();
  driverNotificationSocket = undefined;
  try {
    const currentUser = await requestApi<User>("/api/auth/me");
    if (currentUser.role === "DRIVER") {
      await showDriverDashboard(currentUser);
    } else if (currentUser.role === "DISPATCHER") {
      await showDispatcherDashboard(currentUser);
    } else {
      await showSecurityDashboard(currentUser);
    }
    applicationRoot.querySelector<HTMLButtonElement>(".account button")?.addEventListener("click", async () => {
      try {
        await requestApi("/api/auth/logout", { method: "POST" });
      } finally {
        driverNotificationSocket?.close();
        renderLogin();
      }
    });
  } catch {
    renderLogin();
  }
}

renderLogin();
void loadApplication();
