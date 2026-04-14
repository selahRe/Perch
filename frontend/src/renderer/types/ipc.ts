export type PetEmotion = 'happy' | 'eat' | 'play';

export interface PetUpdatePayload {
  visible: boolean;
  emotion: PetEmotion;
  speak?: string;
}