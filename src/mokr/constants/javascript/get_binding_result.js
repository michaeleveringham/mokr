function deliverResult(name, seq, result) {
    window[name]['callbacks'].get(seq)(result);
    window[name]['callbacks'].delete(seq);
}