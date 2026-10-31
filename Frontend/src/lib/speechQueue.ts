/** Priority speech queue. FR-19..23, FR-28, NFR-ACC-02 */

export type SpeechPriority = "polite" | "assertive";

export interface SpeechItem {
  text: string;
  event?: string;
  priority: SpeechPriority;
}

export class SpeechQueue {
  polite: SpeechItem[] = [];
  current: SpeechItem | null = null;
  held: SpeechItem[] = [];

  enqueue(item: SpeechItem): { cancelCurrent: boolean; next: SpeechItem | null; dropped: SpeechItem[] } {
    if (item.priority === "assertive") {
      const dropped = [...this.polite];
      this.polite = [];
      this.current = item;
      return { cancelCurrent: true, next: item, dropped };
    }

    this.polite.push(item);
    const dropped = this.dropOverflow();
    if (!this.current) {
      return { cancelCurrent: false, next: this.shiftNext(), dropped };
    }
    return { cancelCurrent: false, next: null, dropped };
  }

  shiftNext(): SpeechItem | null {
    const next = this.polite.shift() ?? null;
    this.current = next;
    return next;
  }

  hold(item: SpeechItem): void {
    this.held.push(item);
  }

  holdCurrentIfAssertive(): void {
    if (this.current?.priority === "assertive") {
      this.held.push(this.current);
    }
    this.current = null;
  }

  parkUnplayed(): void {
    this.holdCurrentIfAssertive();
    if (this.polite.length) {
      this.held.push(...this.polite);
      this.polite = [];
    }
  }

  takeHeld(): SpeechItem[] {
    const items = this.held;
    this.held = [];
    return items;
  }

  clear(options: { held?: boolean } = { held: true }): void {
    this.polite = [];
    this.current = null;
    if (options.held !== false) {
      this.held = [];
    }
  }

  private dropOverflow(): SpeechItem[] {
    const dropped: SpeechItem[] = [];
    while (this.polite.length >= 3) {
      const index = this.polite.findIndex((item) => item.event === "browser_action");
      if (index === -1) {
        break;
      }
      dropped.push(this.polite.splice(index, 1)[0]);
    }
    return dropped;
  }
}
