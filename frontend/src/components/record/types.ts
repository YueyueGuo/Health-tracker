export interface SetDraft {
  key: number;
  weight: string;
  reps: string;
  rpe: string;
  performed_at: string | null;
}

export interface ExerciseDraft {
  key: number;
  name: string;
  notes: string;
  showNotes: boolean;
  /** True when this card is supersetted with the next card. */
  linkedToNext: boolean;
  sets: SetDraft[];
}
