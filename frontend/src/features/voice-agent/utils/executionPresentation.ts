import { VoiceAgentIconName } from "../types/voiceAgent.types";

/** Pick an icon for an execution from its backend tool name / action type. */
export function iconForToolName(name: string): VoiceAgentIconName {
  const n = (name || "").toLowerCase();
  if (n.includes("mail") || n.includes("email")) return "mail";
  if (n.includes("calendar") || n.includes("schedule") || n.includes("event"))
    return "calendar";
  if (n.includes("drive")) return "spark";
  if (n.includes("agent")) return "slack";
  if (n.includes("imessage") || n.includes("message")) return "user";
  if (n.includes("call")) return "waveform";
  if (n.includes("contact")) return "contact";
  return "lock";
}

/** Human-friendly capability label for an execution's tool name / action type. */
export function labelForToolName(name: string): string {
  const n = (name || "").toLowerCase();
  if (n.includes("mail") || n.includes("email")) return "Email";
  if (n.includes("calendar") || n.includes("schedule")) return "Calendar";
  if (n.includes("drive")) return "Google Drive";
  if (n.includes("agent")) return "Agentverse";
  if (n.includes("imessage")) return "Messages";
  if (n.includes("call")) return "Call";
  if (n.includes("contact")) return "Contacts";
  return "Action";
}
