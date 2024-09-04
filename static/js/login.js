
$(document).ready(function(){
    $('#login-form').submit(function(event) {
        event.preventDefault();

        const password = $('#password').val();
        const nextUrl = new URLSearchParams(window.location.search).get('next_url') || '/';

        $.ajax({
            type: 'POST',
            url: '/login',
            data: JSON.stringify({"password": password, "next_url": nextUrl}),
            contentType: 'application/json',
            xhrFields: { withCredentials: true },
            success: function(response) {
                if (response.status_code == 401) {
                    $('#feedback').text(response.detail);
                    $('#feedback').addClass("text-danger");
                    $('#card').addClass('border-danger');
                    console.log($('#feedback'));
                }

            },
            error: function(response) {
                console.log("Response", response);
                $('#feedback').text("Unknown error, try again later.");
                $('#feedback').addClass("text-danger");
                $('#card').addClass('border-danger');
            }
        });
    });
});