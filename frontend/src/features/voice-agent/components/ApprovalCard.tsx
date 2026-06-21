import { ApprovalRequest, EmailDraftLifecycleStatus } from '../types/voiceAgent.types';
import { iconForToolName, labelForToolName } from '../utils/executionPresentation';
import { VoiceAgentIcon } from './VoiceAgentIcons';

function previewTypeLabel(emailType: string): string {
  switch (emailType) {
    case 'notification':
      return 'Notification Email';
    case 'agent_message':
      return 'Agent Message';
    default:
      return 'User Request';
  }
}

function statusLabelForDraft(status: EmailDraftLifecycleStatus) {
  switch (status) {
    case 'approved':
      return 'Approved';
    case 'rejected':
      return 'Cancelled';
    default:
      return 'Voice Confirmation Pending';
  }
}

function statusClassNameForDraft(status: EmailDraftLifecycleStatus) {
  switch (status) {
    case 'approved':
      return 'border-[#3f5e44] bg-[#0f1a12] text-[#9ed3a6]';
    case 'rejected':
      return 'border-[#5e302b] bg-[#1f1210] text-[#d99a93]';
    default:
      return 'border-[#a07e3a] bg-[#1c1608] text-[#e9cf94]';
  }
}

export function ApprovalCard({
  request,
  draftStatus = 'pending',
  onApprove,
  onCancel,
}: {
  request: ApprovalRequest;
  draftStatus?: EmailDraftLifecycleStatus;
  onApprove?: () => void;
  onCancel?: () => void;
}) {
  const preview = request.preview;
  const statusLabel = statusLabelForDraft(draftStatus);
  const statusClassName = statusClassNameForDraft(draftStatus);
  const capabilityLabel = labelForToolName(request.toolName);
  const iconName = iconForToolName(request.toolName);
  const isEmailLike =
    request.preview?.emailType !== 'agent_message' &&
    capabilityLabel === 'Email';
  const recipientLabel = isEmailLike ? 'Recipient' : 'Send to';
  const voiceHint =
    draftStatus === 'pending'
      ? "Say 'send it', 'cancel it', or tell Désir what to change."
      : draftStatus === 'approved'
        ? 'Confirmed by voice.'
        : 'Cancelled by voice.';

  return (
    <div
      className="rounded-[10px] border bg-[#111111] p-5"
      style={{ borderColor: 'var(--voice-agent-border)' }}
    >
      <div className="flex items-start gap-4">
        <div className="mt-0.5 rounded-lg border border-white/10 bg-white/5 p-3 text-[#d4d4d4]">
          <VoiceAgentIcon name={iconName} className="h-[22px] w-[22px]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-[10px] uppercase tracking-[1.2px] text-[#737373]">
              {capabilityLabel} · {request.title}
            </div>
            <div className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[1px] ${statusClassName}`}>
              {statusLabel}
            </div>
          </div>
          <div className="royal-display mt-2 text-[28px] font-semibold tracking-[0.01em] text-(--voice-agent-gold-bright)">
            Dispatch for Approval
          </div>
          <div className="mt-2 max-w-140 text-[12px] leading-6 text-[#a3a3a3]">
            {request.detail}
          </div>
          <div className="mt-2 text-[11px] text-[#737373]">{request.summary}</div>
          <div className="mt-3 rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-[11px] text-[#d4d4d4]">
            {voiceHint}
          </div>
          {draftStatus === 'pending' && (onApprove || onCancel) ? (
            <div className="mt-4 flex flex-wrap gap-3">
              {onApprove ? (
                <button
                  type="button"
                  onClick={onApprove}
                  className="rounded-sm border border-[#3f5e44] bg-[#0f1a12] px-4 py-2 text-[11px] font-medium uppercase tracking-[1px] text-[#9ed3a6] transition hover:bg-[#14301a]"
                >
                  Approve
                </button>
              ) : null}
              {onCancel ? (
                <button
                  type="button"
                  onClick={onCancel}
                  className="rounded-sm border border-[#5e302b] bg-[#1f1210] px-4 py-2 text-[11px] font-medium uppercase tracking-[1px] text-[#d99a93] transition hover:bg-[#2a1515]"
                >
                  Cancel
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      {preview ? (
        <div
          className="mt-6 rounded-[10px] border bg-black/20 p-4"
          style={{ borderColor: 'var(--voice-agent-border)' }}
        >
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
            <div className="grid gap-2">
              <div className="text-[11px] font-medium uppercase tracking-[1px] text-[#737373]">
                {recipientLabel}
              </div>
              <div
                className="rounded-md border bg-[#0d0d0d] px-4 py-3 text-[12px] text-white break-all"
                style={{ borderColor: 'var(--voice-agent-border)' }}
              >
                {preview.to}
              </div>
            </div>
            <div className="grid gap-2">
              <div className="text-[11px] font-medium uppercase tracking-[1px] text-[#737373]">
                Type
              </div>
              <div
                className="rounded-md border bg-[#0d0d0d] px-4 py-3 text-[12px] text-white"
                style={{ borderColor: 'var(--voice-agent-border)' }}
              >
                {previewTypeLabel(preview.emailType)}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-2">
            <div className="text-[11px] font-medium uppercase tracking-[1px] text-[#737373]">
              Subject
            </div>
            <div
              className="rounded-md border bg-[#0d0d0d] px-4 py-3 text-[12px] text-white"
              style={{ borderColor: 'var(--voice-agent-border)' }}
            >
              {preview.subject}
            </div>
          </div>

          {preview.link ? (
            <div className="mt-4 grid gap-2">
              <div className="text-[11px] font-medium uppercase tracking-[1px] text-[#737373]">
                Link
              </div>
              <div
                className="rounded-md border bg-[#0d0d0d] px-4 py-3 text-[12px] text-white break-all"
                style={{ borderColor: 'var(--voice-agent-border)' }}
              >
                {preview.link}
              </div>
            </div>
          ) : null}

          <div className="mt-4 grid gap-2">
            <div className="text-[11px] font-medium uppercase tracking-[1px] text-[#737373]">
              Message
            </div>
            <div
              className="max-h-80 min-h-55 overflow-auto whitespace-pre-wrap rounded-md border bg-[#0d0d0d] px-4 py-3 text-[12px] leading-6 text-white"
              style={{ borderColor: 'var(--voice-agent-border)' }}
            >
              {preview.body}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
