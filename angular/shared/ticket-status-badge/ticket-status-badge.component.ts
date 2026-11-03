import { Component, computed, input } from '@angular/core';
import { NgIconComponent } from '@ng-icons/core';

type TicketStatus = 'WON' | 'LOST' | 'PENDING' | 'PARTIAL' | 'VOID' | 'ERROR';

interface StatusConfig {
  icon: string;
  badge: string;
  icon_cls: string;
}

const STATUS_MAP: Record<TicketStatus, StatusConfig> = {
  WON: {
    icon: 'lucideCircleCheckBig',
    badge: 'badge-won',
    icon_cls: 'icon-won',
  },
  LOST: {
    icon: 'lucideCircleX',
    badge: 'badge-lost',
    icon_cls: 'icon-lost',
  },
  PENDING: {
    icon: 'lucideClock',
    badge: 'badge-pending',
    icon_cls: 'icon-pending',
  },
  PARTIAL: {
    icon: 'lucideCircleMinus',
    badge: 'badge-partial',
    icon_cls: 'icon-partial',
  },
  VOID: {
    icon: 'lucideBan',
    badge: 'badge-void',
    icon_cls: 'icon-void',
  },
  ERROR: {
    icon: 'lucideCircleAlert',
    badge: 'badge-error',
    icon_cls: 'icon-error',
  },
};

const FALLBACK: StatusConfig = {
  icon: 'lucideClock',
  badge: 'badge-pending',
  icon_cls: 'icon-pending',
};

@Component({
  selector: 'app-ticket-status-badge',
  imports: [NgIconComponent],
  template: `
    <span [class]="'status-badge ' + cfg().badge">
      <ng-icon [name]="cfg().icon" [class]="'status-icon ' + cfg().icon_cls" />
      {{ status() }}
    </span>
  `,
  styleUrl: './ticket-status-badge.component.scss',
})
export class TicketStatusBadgeComponent {
  readonly status = input.required<string>();

  readonly cfg = computed<StatusConfig>(
    () => STATUS_MAP[(this.status().toUpperCase() as TicketStatus) ?? ''] ?? FALLBACK,
  );
}
