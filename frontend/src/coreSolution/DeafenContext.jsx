import { createContext, useContext, useState } from 'react';
import { RoomAudioRenderer } from '@livekit/components-react';

const Ctx = createContext({ deafened: false, setDeafened: () => { } });
export const useDeafen = () => useContext(Ctx);

export function DeafenProvider({ children }) {
    const [deafened, setDeafened] = useState(false);
    return <Ctx.Provider value={{ deafened, setDeafened }}>{children}</Ctx.Provider>;
}

// plays the agent's voice; silent while deafened
export function DeafenAudioRenderer() {
    const { deafened } = useDeafen();
    return <RoomAudioRenderer muted={deafened} volume={deafened ? 0 : 1} />;
}