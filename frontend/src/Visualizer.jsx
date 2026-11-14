// >>> THE FILE YOUR FRONTEND FRIEND SHOULD EDIT FIRST <<<
// Everything agent-related (state, audio track) comes from the hook below.
import { BarVisualizer, useVoiceAssistant } from '@livekit/components-react';

export default function Visualizer() {
  // state: 'disconnected' | 'connecting' | 'initializing' | 'listening' | 'thinking' | 'speaking'
  const { state, audioTrack } = useVoiceAssistant();

  return (
    <>
      <BarVisualizer
        state={state}
        barCount={7}
        trackRef={audioTrack}
        style={{ height: 64, width: 160 }}
      />
      <p className="state">{state}</p>
    </>
  );
}

/* ---------------------------------------------------------------------------
  To use the Agents UI wave visualizer instead (requires Tailwind + shadcn):

    npx shadcn@latest add @agents-ui/agent-audio-visualizer-wave

  import { useVoiceAssistant } from '@livekit/components-react';
  import { AgentAudioVisualizerWave } from '@/components/agents-ui/agent-audio-visualizer-wave';

  const { state } = useVoiceAssistant();
  <AgentAudioVisualizerWave
    size="xl"
    color="#ff3700"
    colorShift={0.53}
    lineWidth={6.4}
    state={state}     // <- real state instead of the hard-coded "speaking"
    className="mx-auto aspect-square size-auto h-full"
  />
--------------------------------------------------------------------------- */
