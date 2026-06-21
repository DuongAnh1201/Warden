import {
  ApprovalRequest,
  ExecutionRecord,
  TimelineStep,
  TimelineStepStatus,
} from '../types/voiceAgent.types';
import {iconForToolName} from '../utils/executionPresentation';
import {voiceAgentLayoutTokens} from '../utils/voiceAgentLayoutTokens';
import {ApprovalCard} from './ApprovalCard';
import {ExecutionTimelineItem} from './ExecutionTimelineItem';

function statusToStep(status: ExecutionRecord['status']): {
  step: TimelineStepStatus;
  badge: string;
} {
  switch (status) {
    case 'approved':
      return {step: 'completed', badge: 'APPROVED'};
    case 'rejected':
      return {step: 'error', badge: 'REJECTED'};
    default:
      return {step: 'active', badge: 'PENDING'};
  }
}

function executionToTimelineStep(execution: ExecutionRecord): TimelineStep {
  const {step, badge} = statusToStep(execution.status);
  return {
    id: execution.id,
    title: execution.title,
    subtitle: execution.summary,
    icon: iconForToolName(execution.toolName),
    status: step,
    badgeLabel: badge,
  };
}

export function ExecutionTimeline({
  jobId,
  executions,
  approvalRequest,
  onApprove,
  onCancel,
}: {
  jobId: string;
  executions: ExecutionRecord[];
  approvalRequest: ApprovalRequest | null;
  onApprove?: () => void;
  onCancel?: () => void;
}) {
  return (
    <section className="flex min-h-[360px] flex-col bg-[var(--voice-agent-center-shell)] xl:min-h-0 xl:overflow-hidden">
      <div
        className="flex items-center justify-between border-b px-4 pb-[17px] pt-4"
        style={{borderColor: 'var(--voice-agent-border)'}}
      >
        <span className="royal-display text-[15px] italic tracking-[0.1em] text-(--voice-agent-gold)">
          Field Log
        </span>
        <span
          className="text-[11px] text-[#525252]"
          style={{fontFamily: 'var(--font-voice-agent-mono)'}}
        >
          {executions.length > 0 ? `${executions.length} logged` : jobId}
        </span>
      </div>

      <div
        className="relative min-h-0 flex-1 overflow-auto"
        style={{padding: voiceAgentLayoutTokens.timelinePadding}}
      >
        <div
          className="absolute bottom-0 top-0 w-px"
          style={{left: voiceAgentLayoutTokens.timelinePadding + 19, backgroundColor: 'var(--voice-agent-border)'}}
        />

        {executions.length === 0 ? (
          <div className="relative flex h-full min-h-[240px] items-center pl-16">
            <div>
              <div className="royal-display text-[20px] italic text-(--voice-agent-gold-bright)">
                Awaiting your orders
              </div>
              <div className="mt-2 text-[11px] leading-relaxed text-[#8a8170]">
                Touch the orb to open the line. Every move Désir makes on your behalf is logged here, step by step.
              </div>
            </div>
          </div>
        ) : (
          <div className="relative flex flex-col gap-8">
            {executions.map((execution) => {
              const isPending =
                execution.status === 'pending' &&
                approvalRequest?.id === execution.id;
              return (
                <ExecutionTimelineItem
                  key={execution.id}
                  step={executionToTimelineStep(execution)}
                >
                  {isPending ? (
                    <ApprovalCard
                      request={approvalRequest}
                      draftStatus="pending"
                      onApprove={onApprove}
                      onCancel={onCancel}
                    />
                  ) : null}
                </ExecutionTimelineItem>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
