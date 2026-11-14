"""Round 14: the server decides who answers (flameo tool, RAG, both, a clarifying question, or "not in the data").

    understand.py  words -> entities + intent + context (no model)
    session.py     what the conversation is about (psi, material, scenario, the last offer, a pending clarify)
    answer.py      run the branches in parallel, merge, broaden, probe, clarify, log
"""
