import { useRef } from 'react';
import { useVoiceAssistant, useLocalParticipant, useIsSpeaking } from '@livekit/components-react';

const MAP = {
    connecting: 'connecting',
    initializing: 'connecting',
    'pre-connect-buffering': 'connecting',
    idle: 'idle',
    listening: 'listening',
    thinking: 'thinking',
    speaking: 'speaking',
};

export function useAgentState() {
    const { state } = useVoiceAssistant();
    const { localParticipant } = useLocalParticipant();
    const userSpeaking = useIsSpeaking(localParticipant);   // true only while your mic is picking up speech
    const wasUp = useRef(false);
    if (state !== 'disconnected' && state !== 'connecting') wasUp.current = true;
    // before the first connection, "disconnected" just means the token is still in flight
    if (state === 'disconnected') return wasUp.current ? 'disconnected' : 'connecting';
    // LiveKit "listening" = agent is waiting for you. Only show it while you are really talking.
    if (state === 'listening') return userSpeaking ? 'listening' : 'idle';
    return MAP[state] ?? 'idle';
}