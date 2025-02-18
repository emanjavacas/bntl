
$(document).ready(function(){

    function registerError(msg) {
        $('#feedback').text(msg).addClass("text-danger");
        $('#card').addClass('border-danger');
    }

    $('#login-form').submit(function(event) {
        event.preventDefault();
        
        $('#loadingModal').modal("show");

        const password = $('#password').val();
        const nextUrl = new URLSearchParams(window.location.search).get('next_url') || '/';

        $.ajax({
            type: 'POST',
            url: '/login',
            data: JSON.stringify({"password": password, "next_url": nextUrl}),
            contentType: 'application/json',
            xhrFields: { withCredentials: true },
            success: function(response) {
                $('#loadingModal').modal("hide");
                if (response.status_code == 303) {
                    window.location.href = nextUrl;
                } else {
                    registerError("Unknown response.")
                }
            },
            error: function(resp) {
                $('#loadingModal').modal("hide");
                resp = JSON.parse(resp.responseText);
                registerError(resp.detail);
            }
        });
    });
});