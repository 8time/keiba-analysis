//===========================================================
// 選択方式の表示切り替え処理
//===========================================================

//===========================================================
// Docment Readyになったときに処理するもの
//===========================================================
$(document).ready(function ()
{
	//オッズ表示時の買い目チェック
	//cart_get_itemlist( _odds_ranking_cart_group_bet, init_select_kaime );
});

//===========================================================
// オッズ検索結果にて、
// すでにチェック済みの買い目にチェックを入れる
// in: _cart       = cart_get_itemlist()の戻り(item_id)
//     _aryID['0'] = チェック対象のchkboxのidタグ検索キー
//===========================================================
function init_select_kaime_ranking( _cart )
{
    $("[id^='check_']").each(function()
	{
		var chkbox 	= $(this);
		var count 	= chkbox.val();
	    for(var item_id in _cart)
		{

			if (item_id == count)
			{// すでにチェック済みの買い目と一致したとき

				chkbox.prop("checked", true);	// 該当chkboxをチェック
				chkbox.parent().parent().addClass('Selected');
			}
	    }
    });
	view_check_count_ranking();		// チェック数をカウント(初期表示)
}

//------------------------------------------------------------
// 買い目点数のカウント・表示
//------------------------------------------------------------
function view_check_count_ranking()
{
    var cnt = 0;
    $("[id^='check_']").each(function()
	{
		var chkbox = $(this);
		if ( chkbox.prop("checked") == true )
		{
			cnt++;
		}
    });
    $('#odds_select').text( cnt);
    //51件以上の買い目が選択されている場合はアラートメッセージ
    if(cnt>255)
    {
        $('#caution_50bet').css("display", "block");
    }
    else
    {
        $('#caution_50bet').css("display", "none");
    }
}

function update_cart_checkbox_ranking( _group, _item_id, _item_value, _client_data, _checked, id )
{
	// var select = $('select.' + _menu_class);
	var ele_id = "check_"+id;
    if(true == _checked){
	cart_add_item( _group, _item_id, _item_value, '', _client_data );
		$(this).each(function() {
			$("#"+ele_id).parent().parent().addClass('Selected');
		});
    }else{
	cart_remove_item( _group, _item_id );
		$(this).each(function() {
			
			$("#"+ele_id).parent().parent().removeClass('Selected');
		});
    }
}
// $(function() {
//     $('.HorseCheck_Select').on("click", function() {
//     	if ($(this).prop('checked')) {
//     		$(this).each(function() {
//     			$(this).parent().parent().addClass('Selected');
//     		});
//     	} else {
//     		$(this).each(function() {
//     			$(this).parent().parent().removeClass('Selected');
//     		});
//     	}
//     });
// });
