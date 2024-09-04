
$(document).ready(function() {

    function generateSessionId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }    

    // get session id from local storage
    function getSessionId() {
        let sessionId = localStorage.getItem("session_id");
        if (!sessionId) {
            sessionId = generateSessionId();
            localStorage.setItem("session_id", sessionId);
        }
        return sessionId;
    }

    // make sure session id is added to all routes
    $.ajaxSetup({
        beforeSend: function(xhr) {
            const sessionId = getSessionId();
            xhr.setRequestHeader('X-Session-ID', sessionId);
        }
    });

});