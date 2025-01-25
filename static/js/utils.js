
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

// toast
function showToast(message, type="danger") {
    // Define the toast HTML
    const toastHTML = `
    <div class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="3000">
        <div class="toast-header">
            <strong class="me-auto">⚠️ Ooops</strong>
            <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    </div>`;

    // Append the toast to the container
    $('.toast-container').append(toastHTML);

    // Initialize and show the toast
    const toastElement = $('.toast').last(); // Select the newly added toast
    const toast = new bootstrap.Toast(toastElement[0]); // Initialize it
    toast.show(); // Show the toast

    // Remove the toast from the DOM after it disappears
    toastElement.on('hidden.bs.toast', function () {
        $(this).remove();
    });
}
